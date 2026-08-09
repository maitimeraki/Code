"""Secure download/extraction of remote plugin assets.

All network access is HTTPS-only, runs with a hard timeout, uses
``subprocess`` list-args (never shell), and validates every extracted path
against path traversal before writing.
"""

import subprocess
import tarfile
import tempfile
from pathlib import Path

from harness.config import URLFetchError, http_get_string, is_url

# Substrings that never belong in a remote-controlled path/URL segment.
_FORBIDDEN = ("..", "~", "\\", "\x00", "\n", "\r")
# Shell metacharacters — reject anything that could be reinterpreted if the
# value ever reached a command line (it never does, but defense in depth).
_SHELL_META = (";", "&", "|", "`", "$", ">", "<", '"', "'", "*", "?")


def validate_plugin_ref(ref: str) -> None:
    """Reject obviously malicious plugin source strings.

    Raises :class:`ValueError` if the reference contains path traversal,
    shell metacharacters, or control characters. Anything that survives this
    guard is passed only as a single subprocess argument (list form), never
    through a shell.
    """
    if any(seg in ref for seg in _FORBIDDEN):
        raise ValueError("Plugin source contains forbidden path characters")
    if any(c in ref for c in _SHELL_META):
        raise ValueError("Plugin source contains shell metacharacters")


def validate_https_url(url: str) -> None:
    """Reject non-HTTPS or clearly malformed URLs early."""
    if not is_url(url):
        raise URLFetchError(f"Unsupported URL scheme: {url.split(':', 1)[0]}://")
    validate_plugin_ref(url)


def _safe_dest(dest: Path) -> Path:
    """Resolve dest to an absolute path (no CWD-relative surprises)."""
    return dest.expanduser().resolve()


def fetch_text(url: str, timeout: int = 10) -> str:
    """Fetch a UTF-8 text file (e.g. marketplace.json) over HTTPS."""
    validate_https_url(url)
    return http_get_string(url, timeout=timeout)


def git_clone(url: str, dest: Path, timeout: int = 60) -> None:
    """Shallow-clone a git repo into ``dest`` (list-args, never shell)."""
    validate_https_url(url)
    dest = _safe_dest(dest)
    dest.parent.mkdir(parents=True, exist_ok=True)
    cmd = ["git", "clone", "--depth", "1", "--quiet", "--", url, str(dest)]
    try:
        proc = subprocess.run(cmd, capture_output=True, timeout=timeout, text=True)
    except subprocess.TimeoutExpired:
        raise URLFetchError(f"git clone timed out after {timeout}s") from None
    if proc.returncode != 0:
        msg = (proc.stderr or "unknown error").strip().splitlines()
        raise URLFetchError(f"git clone failed: {msg[-1] if msg else 'unknown error'}")


def download_tarball(url: str, dest: Path, timeout: int = 60) -> None:
    """Download a .tar.gz over HTTPS and extract it into ``dest`` safely."""
    import io
    import ssl
    import urllib.request

    validate_https_url(url)
    dest = _safe_dest(dest)
    dest.mkdir(parents=True, exist_ok=True)

    ctx = ssl.create_default_context()
    request = urllib.request.Request(
        url, headers={"User-Agent": "harness-plugin-manager/1.0"}
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout, context=ctx) as resp:
            data = resp.read()
    except (urllib.error.URLError, ssl.SSLError, TimeoutError, OSError) as exc:
        raise URLFetchError(
            f"Could not download archive ({type(exc).__name__})"
        ) from exc

    _extract_tar_safe(io.BytesIO(data), dest)


def _extract_tar_safe(stream, dest: Path) -> None:
    """Extract a tar stream, rejecting any path that escapes ``dest``."""
    dest = _safe_dest(dest)
    with tarfile.open(fileobj=stream, mode="r:gz") as tar:
        for member in tar.getmembers():
            target = (dest / member.name).resolve()
            if not target.is_relative_to(dest):
                raise URLFetchError(
                    f"Archive contains path traversal: {member.name!r}"
                )
            if member.issym() or member.islnk():
                raise URLFetchError(
                    f"Archive contains a symlink: {member.name!r}"
                )
        tar.extractall(dest, filter="data")


def temp_workdir() -> Path:
    """A private temp dir for downloading/extracting before final install."""
    return Path(tempfile.mkdtemp(prefix="harness-plugin-"))