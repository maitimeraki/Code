"""Configuration management with Pydantic."""

import json
import os
from typing import Any
from pydantic_settings import BaseSettings
from pydantic import BaseModel, Field
from pathlib import Path


_settings_file_cache: dict[str, Any] | None = None

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


def load_settings_file() -> dict[str, Any]:
    """Load entire settings.json file once at startup, cache it.

    Returns all fields (env, hooks, permissions, enabledPlugins, etc.)
    dynamically. As user adds new fields over time, they work automatically.
    Reads from disk only once per process; subsequent calls return cached copy.
    """
    global _settings_file_cache
    if _settings_file_cache is not None:
        return _settings_file_cache

    settings = get_settings()
    settings_path = settings.get_settings_file_path()

    if settings_path.exists():
        try:
            with open(settings_path, "r", encoding="utf-8") as f:
                _settings_file_cache = json.load(f)  
        except (json.JSONDecodeError, OSError):
            print("Line:44")
            _settings_file_cache = {"env": dict(_DEFAULT_ENV_BLOCK)}
    else:
        _settings_file_cache = {"env": dict(_DEFAULT_ENV_BLOCK)}
        print("Line:48")
        try:
            settings_path.write_text(json.dumps(_settings_file_cache, indent=2))
        except OSError:
            pass

    return _settings_file_cache


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
    tool_timeout_seconds: int = Field(default=30, alias="TOOL_TIMEOUT_SECONDS")

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


def get_settings() -> Settings:
    """Load and return settings singleton."""
    return Settings()
