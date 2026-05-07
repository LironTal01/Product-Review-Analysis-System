"""Configuration management for PRAS."""

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application settings loaded from environment variables."""

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8")

    app_name: str = "PRAS"
    app_env: str = "development"
    debug: bool = True
    log_level: str = "INFO"

    openai_api_key: str = ""

    database_url: str = ""
    redis_url: str = ""


@lru_cache
def get_settings() -> Settings:
    """Get cached settings instance."""
    return Settings()
