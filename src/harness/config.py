"""Configuration management with Pydantic."""

from pydantic_settings import BaseSettings
from pydantic import Field
from pathlib import Path


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


def get_settings() -> Settings:
    """Load and return settings singleton."""
    return Settings()
