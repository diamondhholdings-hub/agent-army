"""Application configuration via Pydantic BaseSettings."""

from enum import Enum
from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Environment(str, Enum):
    development = "development"
    staging = "staging"
    production = "production"


class Settings(BaseSettings):
    """Application settings loaded from environment variables and .env file."""

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8")

    # Database
    DATABASE_URL: str = "postgresql+asyncpg://agent_army:agent_army_dev@localhost:5432/agent_army"

    # Redis
    REDIS_URL: str = "redis://localhost:6379/0"

    # Environment
    ENVIRONMENT: Environment = Environment.development

    # Logging
    LOG_LEVEL: str = "INFO"

    # Multi-tenant schema config
    SHARED_SCHEMA: str = "shared"


@lru_cache
def get_settings() -> Settings:
    """Singleton settings instance."""
    return Settings()
