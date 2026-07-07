"""Configuration management with Pydantic."""

from pydantic_settings import BaseSettings
from pydantic import Field
from pathlib import Path


class Settings(BaseSettings):
    """Application configuration from environment variables."""

    # LLM Providers
    claude_api_key: str = Field(default="", alias="CLAUDE_API_KEY")
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

    # Paths
    data_dir: Path = Field(default=Path("data"), alias="DATA_DIR")
    templates_dir: Path = Field(default=Path("templates"), alias="TEMPLATES_DIR")

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"
        case_sensitive = False

    def validate_api_keys(self) -> bool:
        """Check at least one LLM provider is configured."""
        if not (self.claude_api_key or self.openai_api_key or self.azure_api_key):
            raise ValueError(
                "At least one LLM API key required: "
                "CLAUDE_API_KEY, OPENAI_API_KEY, or AZURE_API_KEY"
            )
        return True


def get_settings() -> Settings:
    """Load and return settings singleton."""
    return Settings()
