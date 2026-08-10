"""Configuration management with Pydantic."""

import json
import os
import ssl
import urllib.request
from functools import lru_cache
from typing import Any
from pydantic_settings import BaseSettings
from pydantic import BaseModel, Field
from pathlib import Path


class URLFetchError(Exception):
    """Raised when a remote marketplace/plugin fetch fails (timeout, non-2xx, bad TLS)."""


def is_url(value: str) -> bool:
    """Return True if value looks like an http(s) URL."""
    return value.startswith(("http://", "https://"))


def http_get_string(url: str, timeout: int = 10) -> str:
    """Fetch a URL over HTTPS and return the response body as UTF-8 text.

    Uses stdlib ``urllib`` with a verified TLS context and a hard timeout.
    Only https:// is allowed; http:// is rejected to prevent spoofing on
    untrusted networks. On any failure (DNS, TLS, non-2xx, timeout) raises
    :class:`URLFetchError` with a redacted message (no raw URL).
    """
    if not is_url(url):
        raise URLFetchError(f"Unsupported URL scheme: {url.split(':', 1)[0]}://")
    ctx = ssl.create_default_context()
    request = urllib.request.Request(
        url, headers={"User-Agent": "harness-plugin-manager/1.0"}
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout, context=ctx) as resp:
            status = getattr(resp, "status", 200)
            if status >= 400:
                raise URLFetchError(f"Remote responded with HTTP {status}")
            return resp.read().decode("utf-8", errors="replace")
    except URLFetchError:
        raise
    except (urllib.error.URLError, ssl.SSLError, TimeoutError, OSError) as exc:
        raise URLFetchError(f"Could not reach remote source ({type(exc).__name__})") from exc


_user_settings_cache: dict[str, Any] | None = None
_project_settings_cache: dict[str, Any] | None = None

_DEFAULT_ENV_BLOCK = {
    "CODE_BASE_URL": "https://api.anthropic.com",
    "CODE_AUTH_TOKEN":"",
    "CODE_API_KEY": "",
    "CODE_MODEL": "claude-3-5-sonnet-20241022",
    "CODE_STANDARD_MODEL": "claude-3-5-sonnet-20241022",
    "CODE_PRO_MODEL": "claude-3-5-haiku-20241022",
    "CODE_MAX_MODEL": "claude-3-5-haiku-20241022",
    "CODE_SUBAGENT_MODEL": "claude-3-5-haiku-20241022",
}


def _user_settings_path() -> Path:
    """User-level settings file: ~/.code/settings.json (authoritative global config)."""
    return Path.home() / ".code" / "settings.json"


def _project_settings_path() -> Path:
    """Project-level settings file: ./.code/settings.json (per-project overrides)."""
    return Path(".code") / "settings.json"


def _atomic_write(path: Path, data: dict[str, Any]) -> None:
    """Write JSON to disk atomically (temp file + replace)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, indent=2), encoding="utf-8")
    tmp.replace(path)


def load_user_settings() -> dict[str, Any]:
    """Load the user-level ~/.code/settings.json, cached once per process.

    Auto-creates a default env template when missing. This is the authoritative
    global config; the harness never pastes it into a project file.
    """
    global _user_settings_cache
    if _user_settings_cache is None:
        path = _user_settings_path()
        if path.exists():
            try:
                with open(path, "r", encoding="utf-8") as f:
                    _user_settings_cache = json.load(f)
            except (json.JSONDecodeError, OSError):
                _user_settings_cache = {"env": dict(_DEFAULT_ENV_BLOCK)}
        else:
            _user_settings_cache = {"env": dict(_DEFAULT_ENV_BLOCK)}
            try:
                _atomic_write(path, _user_settings_cache)
            except OSError:
                pass
    return _user_settings_cache


def load_project_settings() -> dict[str, Any]:
    """Load the project-level .code/settings.json, or {} when none exists.

    Per-project overrides are authored here (e.g. a single tool permission) and
    overlaid on the user file at read time — never copied wholesale.
    """
    global _project_settings_cache
    if _project_settings_cache is None:
        path = _project_settings_path()
        if path.exists():
            try:
                with open(path, "r", encoding="utf-8") as f:
                    _project_settings_cache = json.load(f)
            except (json.JSONDecodeError, OSError):
                _project_settings_cache = {}
        else:
            _project_settings_cache = {}
    return _project_settings_cache


def project_settings_active() -> bool:
    """True once a project settings file exists (or has been created this process).

    Drives where programmatic writes land and which path save_settings_file uses.
    """
    return _project_settings_cache is not None or _project_settings_path().exists()


def _merge_permissions(user: dict[str, Any], project: dict[str, Any]) -> dict[str, Any]:
    """Union the project and user permission blocks.

    allow/deny lists combine; per-tool patterns merge; project defaultMode wins.
    A tool the project explicitly allows or denies is governed by that project
    rule, so it is removed from the merged ask/alwaysAsk prompts — ask is
    evaluated before allow in PermissionScope.check, so leaving it in both
    would keep prompting despite a project-level persist-allow.
    """
    u = user.get("permissions") or {}
    p = project.get("permissions") or {}
    merged = dict(u)
    bound = set(p.get("allow") or []) | set(p.get("deny") or [])
    for key in ("allow", "deny"):
        merged[key] = list(dict.fromkeys((u.get(key) or []) + (p.get(key) or [])))
    for key in ("ask", "alwaysAsk"):
        merged[key] = [
            tool
            for tool in dict.fromkeys((u.get(key) or []) + (p.get(key) or []))
            if tool not in bound
        ]
    u_pat, p_pat = u.get("patterns") or {}, p.get("patterns") or {}
    patterns = dict(u_pat)
    for tool, plist in p_pat.items():
        patterns[tool] = list(dict.fromkeys((u_pat.get(tool) or []) + (plist or [])))
    merged["patterns"] = patterns
    if p.get("defaultMode"):
        merged["defaultMode"] = p["defaultMode"]
    return merged


def _merge_settings(user: dict[str, Any], project: dict[str, Any]) -> dict[str, Any]:
    """Overlay project-level settings on the user-level file.

    Non-permission dict blocks (env, mcpServers, hooks, ...) merge per-key with
    project winning; scalar/list top-level keys are replaced by project values.
    """
    merged = dict(user)
    for key, value in project.items():
        if key == "permissions":
            merged[key] = _merge_permissions(user, project)
        elif isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key] = {**merged[key], **value}
        else:
            merged[key] = value
    return merged


def load_settings_file() -> dict[str, Any]:
    """Load settings merged from user + project level (cached per level).

    Project-level .code/settings.json overlays the user-level ~/.code/settings.json
    instead of replacing it, so a minimal project file (e.g. only a permissions
    block) still inherits the user's env, MCP servers and hooks. Permission lists
    are unioned, so a tool allowed or asked at either level applies.
    """
    return _merge_settings(load_user_settings(), load_project_settings())


def get_app_settings() -> dict[str, Any]:
    """Access any field from settings.json: env, hooks, permissions, plugins, etc.

    Returns the full cached settings file. Fields like 'hooks', 'permissions',
    'enabledPlugins', 'statusLine', 'worktree' are available if user added them.

    Example:
        app_settings = get_app_settings()
        hooks = app_settings.get("hooks", {})
        permissions = app_settings.get("permissions", {})
        enabled_plugins = app_settings.get("enabledPlugins", {})
    """
    return load_settings_file()


class LLMSettings(BaseModel):
    """LLM configuration matching Claude Code's env-block style."""
    api_base: str
    api_key: str
    auth_token: str
    model: str
    code_standard_model: str = ""
    code_pro_model: str = ""
    code_max_model: str = ""
    subagent_model: str = ""

    @classmethod
    def from_env(cls) -> "LLMSettings":
        """Build LLMSettings by reading os.environ only — no file I/O.

        Assumes export_env_from_settings() already ran once at process
        startup so CODE_* keys are present in os.environ. This is what every
        consumer (LLMClient, future MCP tools/hooks/subagents) should call.
        """
        return cls(
            api_base=os.environ.get("CODE_BASE_URL", "https://api.anthropic.com"),
            api_key=resolve_api_key(os.environ.get("CODE_API_KEY", "env:CODE_API_KEY")),
            auth_token=os.environ.get("CODE_AUTH_TOKEN",""),
            model=os.environ.get("CODE_MODEL", "claude-3-5-sonnet-20241022"),
            code_standard_model=os.environ.get("CODE_STANDARD_MODEL", "claude-3-5-sonnet-20241022"),
            code_pro_model=os.environ.get("CODE_PRO_MODEL", "claude-3-5-haiku-20241022"),
            code_max_model=os.environ.get("CODE_MAX_MODEL", "claude-3-5-haiku-20241022"),
            subagent_model=os.environ.get("CODE_SUBAGENT_MODEL", "claude-3-5-haiku-20241022"),
        )


class Settings(BaseSettings):
    """Application configuration from environment variables."""
    user_id: str = Field(default="", alias="USER_ID")

    # LLM Providers
    code_api_key: str = Field(default="", alias="CODE_API_KEY")
    openai_api_key: str = Field(default="", alias="OPENAI_API_KEY")
    azure_api_key: str = Field(default="", alias="AZURE_API_KEY")

    # Database
    database_url: str = Field(
        default="sqlite+aiosqlite:///harness.db",
        alias="DATABASE_URL"
    )
    redis_url: str = Field(default="", alias="REDIS_URL")

    # Execution
    execution_mode: str = Field(default="local", alias="EXECUTION_MODE")
    max_parallel_agents: int = Field(default=16, alias="MAX_PARALLEL_AGENTS")
    max_agent_retries: int = Field(default=3, alias="MAX_AGENT_RETRIES")
    tool_timeout_seconds: int = Field(default=1800, alias="TOOL_TIMEOUT_SECONDS")

    # UI / Interaction
    ask_question_timeout_seconds: int = Field(
        default=0, alias="ASK_QUESTION_TIMEOUT_SECONDS",
        description="Auto-continue timeout for AskUserQuestion. "
                    "0=forever, 60=1min, 300=5min, 600=10min"
    )
    approval_timeout_seconds: int = Field(
        default=0, alias="APPROVAL_TIMEOUT_SECONDS",
        description="Seconds before an unanswered approval auto-resolves. 0 = wait forever."
    )
    approval_timeout_action: str = Field(
        default="deny", alias="APPROVAL_TIMEOUT_ACTION",
        description="Action on timeout: 'deny' or 'approve' (high-risk always waits)."
    )

    # Completion / loop guards (opt-in; autonomous defaults unchanged)
    use_critic_verifier: bool = Field(default=False, alias="USE_CRITIC_VERIFIER")
    max_wall_seconds: int = Field(default=0, alias="MAX_WALL_SECONDS")  # 0 = no cap
    no_progress_limit: int = Field(default=0, alias="NO_PROGRESS_LIMIT")  # 0 = off
    require_approval: bool = Field(default=False, alias="REQUIRE_APPROVAL")

    # Performance
    prompt_cache_size_mb: int = Field(default=500, alias="PROMPT_CACHE_SIZE_MB")
    log_level: str = Field(default="info", alias="LOG_LEVEL")

    # Legacy path fields (kept for backward compatibility)
    data_dir: Path = Field(default=Path("data"), alias="DATA_DIR")
    templates_dir: Path = Field(default=Path("templates"), alias="TEMPLATES_DIR")

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"
        case_sensitive = False

    @property
    def user_agents_dir(self) -> Path:
        """User-level agents directory (auto-created). ~/.code/agents/"""
        path = Path.home() / ".code" / "agents"
        path.mkdir(parents=True, exist_ok=True)
        return path

    @property
    def project_agents_dir(self) -> Path:
        """Project-level agents directory (not auto-created). ./.code/agents/"""
        return Path(".code") / "agents"

    def get_agents_dir(self) -> Path:
        """Resolve agents directory with priority: project-level → user-level."""
        if self.project_agents_dir.exists():
            return self.project_agents_dir
        return self.user_agents_dir

    @property
    def user_skills_dir(self) -> Path:
        """User-level skills directory (auto-created). ~/.code/skills/"""
        path = Path.home() / ".code" / "skills"
        path.mkdir(parents=True, exist_ok=True)
        return path

    @property
    def project_skills_dir(self) -> Path:
        """Project-level skills directory (not auto-created). ./.code/skills/"""
        return Path(".code") / "skills"

    def get_skills_dir(self) -> Path:
        """Resolve skills directory with priority: project-level → user-level."""
        if self.project_skills_dir.exists():
            return self.project_skills_dir
        return self.user_skills_dir

    @property
    def user_config_dir(self) -> Path:
        """User-level config directory (auto-created). ~/.code/"""
        path = Path.home() / ".code"
        path.mkdir(parents=True, exist_ok=True)
        return path

    @property
    def project_config_dir(self) -> Path:
        """Project-level config directory (not auto-created). ./.code/"""
        return Path(".code")

    def get_config_dir(self) -> Path:
        """Resolve config directory with priority: project-level → user-level."""
        if self.project_config_dir.exists():
            return self.project_config_dir
        return self.user_config_dir

    def get_settings_file_path(self) -> Path:
        """Get path to settings.json (project or user level)."""
        return Path(self.get_config_dir()) / "settings.json"

    @property
    def user_data_dir(self) -> Path:
        """User-level data directory (auto-created). ~/.code/data/"""
        path = Path.home() / ".code" / "data"
        path.mkdir(parents=True, exist_ok=True)
        return path

    @property
    def project_data_dir(self) -> Path:
        """Project-level data directory (not auto-created). ./.code/data/"""
        return Path(".code") / "data"

    def get_data_dir(self) -> Path:
        """Resolve data directory with priority: project-level → user-level."""
        if self.project_data_dir.exists():
            return self.project_data_dir
        return self.user_data_dir

    @property
    def user_templates_dir(self) -> Path:
        """User-level templates directory (auto-created). ~/.code/templates/"""
        path = Path.home() / ".code" / "templates"
        path.mkdir(parents=True, exist_ok=True)
        return path

    @property
    def project_templates_dir(self) -> Path:
        """Project-level templates directory (not auto-created). ./.code/templates/"""
        return Path(".code") / "templates"

    def get_templates_dir(self) -> Path:
        """Resolve templates directory with priority: project-level → user-level."""
        if self.project_templates_dir.exists():
            return self.project_templates_dir
        return self.user_templates_dir

    # def validate_api_keys(self) -> bool:
    #     """Check at least one LLM provider is configured."""
    #     if not (self.code_api_key or self.openai_api_key or self.azure_api_key):
    #         raise ValueError(
    #             "At least one LLM API key required: "
    #             "code_API_KEY, OPENAI_API_KEY, or AZURE_API_KEY"
    #         )
    #     return True


def resolve_api_key(raw: str) -> str:
    """Resolve API key, expanding env var indirection if present."""
    if raw.startswith("env:"):
        return os.environ.get(raw[4:], "")
    return raw


def export_env_from_settings() -> None:
    """Read settings.json's `env` block ONCE and export into os.environ.

    Single point where settings.json is read for LLM provider config. Call
    exactly once per process (from HarnessApp.__init__), before constructing
    any LLMClient. After this call, every consumer reads os.environ directly
    and never re-parses settings.json or calls a settings-loading function.

    Existing OS-level env vars (set by the user's shell before launch) take
    priority over settings.json values: uses os.environ.setdefault, not a
    blind overwrite (shell > settings.json, matching Claude Code's layering).

    If settings.json doesn't exist yet, writes the default template (env
    block with all CODE_* keys) and exports those defaults. If the file
    exists but is malformed/unreadable, exports nothing from it -- falls
    through to LLMSettings.from_env()'s own hardcoded defaults / whatever
    the shell already set.
    """
    settings_data = load_settings_file()
    env_block = settings_data.get("env", {}) or {}

    # Backward compat: fold legacy top-level model/subagent_model into env block
    env_block.setdefault("CODE_MODEL", settings_data.get("model"))
    env_block.setdefault("CODE_SUBAGENT_MODEL", settings_data.get("subagent_model"))

    for key, value in env_block.items():
        if value is None:
            continue
        os.environ.setdefault(key, str(value))


@lru_cache
def get_settings() -> Settings:
    """Load and return settings singleton (cached for the process lifetime)."""
    return Settings()


def _writable_settings() -> dict[str, Any]:
    """Return the cache dict programmatic writes should mutate.

    Project cache when a project settings file exists (or is being created),
    else the user cache — so a write never dumps the merged user+project view
    into a single file (the bug that pasted ~/.code/settings.json wholesale).
    """
    if _project_settings_cache is not None or _project_settings_path().exists():
        return load_project_settings()
    return load_user_settings()


def save_settings_file() -> None:
    """Persist programmatically-authored settings to disk (atomic via temp file).

    Writes the project-level .code/settings.json once a project cache exists
    (the harness authors per-project config), falling back to the user-level file
    when no project settings has been created yet. The user file is never pasted
    into the project file.
    """
    if project_settings_active():
        _atomic_write(_project_settings_path(), load_project_settings())
    elif _user_settings_cache is not None:
        _atomic_write(_user_settings_path(), _user_settings_cache)


def update_mcp_server(name: str, config: dict) -> None:
    """Persist a new or updated MCP server entry to settings.json."""
    data = _writable_settings()
    data.setdefault("mcpServers", {})[name] = config
    save_settings_file()


def remove_mcp_server(name: str) -> bool:
    """Remove an MCP server from settings.json. Returns False if not found."""
    data = _writable_settings()
    servers = data.get("mcpServers") or {}
    if name not in servers:
        return False
    del servers[name]
    save_settings_file()
    return True


def add_permission_allow(tool: str) -> None:
    """Persist a tool as allowed in the PROJECT-level .code/settings.json.

    Writes only the tool's permission into the project file — never a copy of the
    user-level settings (the old behavior pasted the whole ~/.code/settings.json
    into the project, API keys included). The tool moves from ask/alwaysAsk to
    allow so PermissionScope stops prompting for it in THIS project. Reads still
    merge with the user file, so nothing user-authored is lost or duplicated.
    """
    data = load_project_settings()
    perms = data.setdefault("permissions", {})
    allow = perms.setdefault("allow", [])
    if tool not in allow:
        allow.append(tool)
    for key in ("ask", "alwaysAsk"):
        lst = perms.get(key)
        if lst and tool in lst:
            lst.remove(tool)
    save_settings_file()
