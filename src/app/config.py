"""Application configuration via Pydantic BaseSettings."""

from __future__ import annotations

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

    # JWT Authentication
    JWT_SECRET_KEY: str = "CHANGE-ME-IN-PRODUCTION-use-openssl-rand-hex-32"
    JWT_ALGORITHM: str = "HS256"
    JWT_ACCESS_TOKEN_EXPIRE_MINUTES: int = 30
    JWT_REFRESH_TOKEN_EXPIRE_DAYS: int = 7

    # CORS
    CORS_ALLOWED_ORIGINS: str = "*"

    # LLM Providers
    ANTHROPIC_API_KEY: str = ""
    OPENAI_API_KEY: str = ""
    LLM_TIMEOUT: int = 30
    LLM_MAX_RETRIES: int = 3

    # GCP (for Secret Manager and deployment)
    GCP_PROJECT_ID: str = ""

    # Monitoring
    SENTRY_DSN: str = ""

    # Langfuse (LLM observability and cost tracking)
    LANGFUSE_PUBLIC_KEY: str = ""
    LANGFUSE_SECRET_KEY: str = ""
    LANGFUSE_HOST: str = "https://cloud.langfuse.com"

    # Google Workspace (GSuite) Integration
    GOOGLE_SERVICE_ACCOUNT_FILE: str = ""  # Path to service account JSON key file
    GOOGLE_DELEGATED_USER_EMAIL: str = ""  # Admin email for domain-wide delegation
    GOOGLE_CHAT_SPACE_ID: str = ""  # Default Google Chat space for internal team notifications

    # Notion CRM Integration
    NOTION_TOKEN: str = ""
    NOTION_DATABASE_ID: str = ""

    # Base64-encoded Google service account JSON (for containerized deployments)
    GOOGLE_SERVICE_ACCOUNT_JSON_B64: str = ""

    # Meeting Capabilities -- External Service API Keys (Phase 6)
    RECALL_AI_API_KEY: str = ""
    RECALL_AI_REGION: str = "us-west-2"
    DEEPGRAM_API_KEY: str = ""
    ELEVENLABS_API_KEY: str = ""
    ELEVENLABS_VOICE_ID: str = ""
    HEYGEN_API_KEY: str = ""
    HEYGEN_AVATAR_ID: str = ""  # Default avatar; tenant-specific overrides later
    MEETING_BOT_WEBAPP_URL: str = ""  # URL where the Output Media webapp is hosted
    MEETING_BOT_NAME: str = "Sales Agent"  # Bot display name in meetings
    COMPANY_NAME: str = ""  # Company name for entrance greeting
    RECALL_AI_WEBHOOK_TOKEN: str = ""  # Optional webhook validation token

    def get_service_account_path(self) -> str | None:
        """Return path to Google service account JSON file.

        Prefers GOOGLE_SERVICE_ACCOUNT_FILE (direct path) if set.
        Falls back to decoding GOOGLE_SERVICE_ACCOUNT_JSON_B64 into a temp file
        for containerized deployments where mounting a file is impractical.
        Returns None if neither is configured.
        """
        if self.GOOGLE_SERVICE_ACCOUNT_FILE:
            return self.GOOGLE_SERVICE_ACCOUNT_FILE
        if self.GOOGLE_SERVICE_ACCOUNT_JSON_B64:
            import base64
            import os
            import tempfile

            decoded = base64.b64decode(self.GOOGLE_SERVICE_ACCOUNT_JSON_B64)
            tmp_path = os.path.join(tempfile.gettempdir(), "gcp-service-account.json")
            with open(tmp_path, "wb") as f:
                f.write(decoded)
            return tmp_path
        return None


@lru_cache
def get_settings() -> Settings:
    """Singleton settings instance."""
    return Settings()
