"""Configuration management for PRAS."""

import os
from functools import lru_cache

DEFAULT_APP_NAME = "PRAS"
DEFAULT_APP_ENV = "production"
DEFAULT_LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO")
DEFAULT_LLM_MODEL = os.getenv("OPENAI_LLM_MODEL", "gpt-5-nano")


def _parse_bool(value, default):
    """Parse environment boolean values safely."""
    if value is None:
        return default
    normalized = str(value).strip().lower()
    if normalized in {"1", "true", "yes", "on"}:
        return True
    if normalized in {"0", "false", "no", "off"}:
        return False
    return default


class Settings:
    """Application settings loaded from environment variables."""

    def __init__(self):
        # Application
        self.app_name = os.getenv("APP_NAME", DEFAULT_APP_NAME)
        self.app_env = os.getenv("APP_ENV", DEFAULT_APP_ENV)
        self.log_level = os.getenv("LOG_LEVEL", DEFAULT_LOG_LEVEL)
        self.debug = _parse_bool(os.getenv("DEBUG"), False)
        self.allow_mock_fallback = _parse_bool(os.getenv("ALLOW_MOCK_FALLBACK"), False)

        # External services
        self.openai_api_key = os.getenv("OPENAI_API_KEY", "")
        self.openai_llm_model = os.getenv("OPENAI_LLM_MODEL", DEFAULT_LLM_MODEL)
        self.scraper_api_key = os.getenv("SCRAPER_API_KEY", "")

        # Optional cache; an empty value disables it gracefully
        self.redis_url = os.getenv("REDIS_URL", "")


@lru_cache
def get_settings():
    """Get the cached settings instance."""
    return Settings()
