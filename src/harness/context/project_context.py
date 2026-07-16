"""Project context loader: root discovery, memory files, file tree."""

import subprocess
import os
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Optional, Tuple
import fnmatch
import structlog

logger = structlog.get_logger(__name__)

MAX_TREE_ENTRIES = 500


@dataclass
class ProjectContext:
    """Discovered project context: root, memory, file tree."""
    root: Path
    memory_text: str
    memory_sources: list[Path]
    file_tree: str
    file_count: int
    truncated: bool
    used_git: bool
    scanned_at: datetime


def find_project_root(start: Path, max_levels: int = 20) -> Path:
    """Walk up from start looking for .git or .code marker; fallback to start."""
    current = start.resolve()
    for _ in range(max_levels):
        if (current / ".git").exists() or (current / ".code").exists():
            return current
        if current.parent == current:
            break
        current = current.parent
    return start.resolve()


def _load_memory(root: Path, settings) -> Tuple[str, list[Path]]:
    """Load layered memory: user HARNESS.md, then project HARNESS.md/CLAUDE.md fallback."""
    sources = []
    parts = []

    user_path = settings.user_config_dir / "HARNESS.md"
    if user_path.exists():
        try:
            user_text = user_path.read_text(encoding="utf-8")
            parts.append(user_text)
            sources.append(user_path)
        except OSError as e:
            logger.warning("Failed to read user memory", path=str(user_path), error=str(e))

    project_path = root / "HARNESS.md"
    if not project_path.exists():
        project_path = root / "**.md"

    if project_path.exists():
        try:
            project_text = project_path.read_text(encoding="utf-8")
            if parts:
                parts.append("\n<!-- ---- project-level memory (overrides above) ---- -->\n")
            parts.append(project_text)
            sources.append(project_path)
        except OSError as e:
            logger.warning("Failed to read project memory", path=str(project_path), error=str(e))

    return "".join(parts), sources


def _build_file_tree_git(root: Path) -> Optional[Tuple[str, int, bool]]:
    """Try git ls-files; returns (tree, count, False) or None on failure."""
    try:
        result = subprocess.run(
            ["git", "ls-files", "--cached", "--others", "--exclude-standard"],
            cwd=root,
            capture_output=True,
            text=True,
            timeout=5,
        )
        if result.returncode != 0:
            return None

        paths = sorted([p.strip() for p in result.stdout.splitlines() if p.strip()])
        if len(paths) > MAX_TREE_ENTRIES:
            tree_text = "\n".join(paths[:MAX_TREE_ENTRIES])
            tree_text += f"\n... ({len(paths) - MAX_TREE_ENTRIES} more files truncated)"
            return tree_text, MAX_TREE_ENTRIES, True

        return "\n".join(paths), len(paths), False

    except (subprocess.TimeoutExpired, FileNotFoundError, subprocess.CalledProcessError):
        return None


def _build_file_tree_walk(root: Path) -> Tuple[str, int, bool]:
    """Fallback: bounded os.walk with exclusions and depth limit."""
    EXCLUDE = {".git", "node_modules", "__pycache__", "venv", ".venv", "dist", "build",
               ".pytest_cache", ".mypy_cache", "*.egg-info"}

    def should_exclude(name: str) -> bool:
        for pattern in EXCLUDE:
            if fnmatch.fnmatch(name, pattern) or fnmatch.fnmatch(name, pattern + "/"):
                return True
        return False

    paths = []
    max_depth = 4

    for dirpath, dirnames, filenames in os.walk(root):
        depth = len(Path(dirpath).relative_to(root).parts)
        if depth > max_depth:
            break

        dirnames[:] = [d for d in dirnames if not should_exclude(d)]

        for fname in filenames:
            if should_exclude(fname):
                continue
            rel_path = Path(dirpath).relative_to(root) / fname
            paths.append(rel_path.as_posix())
            if len(paths) >= MAX_TREE_ENTRIES:
                tree_text = "\n".join(sorted(paths))
                tree_text += f"\n... ({len(paths) - MAX_TREE_ENTRIES} more files truncated)"
                return tree_text, MAX_TREE_ENTRIES, True

    tree_text = "\n".join(sorted(paths))
    return tree_text, len(paths), False


def load_project_context(start_dir: Path, settings=None) -> ProjectContext:
    """Load project context once: root, memory, file tree."""
    if settings is None:
        from harness.config import get_settings
        settings = get_settings()

    root = find_project_root(start_dir)
    memory_text, memory_sources = _load_memory(root, settings)

    git_result = _build_file_tree_git(root)
    if git_result is not None:
        file_tree, file_count, truncated = git_result
        used_git = True
    else:
        file_tree, file_count, truncated = _build_file_tree_walk(root)
        used_git = False

    return ProjectContext(
        root=root,
        memory_text=memory_text,
        memory_sources=memory_sources,
        file_tree=file_tree,
        file_count=file_count,
        truncated=truncated,
        used_git=used_git,
        scanned_at=datetime.now(),
    )
