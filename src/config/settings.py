"""Configuration settings using Pydantic with environment variable loading."""

from functools import lru_cache
from typing import List

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application settings loaded from environment variables and .env file."""

    # Polymarket API Configuration
    polymarket_api_host: str = "https://clob.polymarket.com"
    polymarket_api_key: str | None = None

    # Database Configuration
    database_url: str = "sqlite:///data/polymarket.db"

    # Rate Limiting Configuration
    # Conservative: 80% of 60/s sustained limit to avoid throttling
    max_requests_per_second: int = 50

    # Retry Configuration
    retry_max_attempts: int = 5
    retry_backoff_multiplier: float = 2.0
    retry_min_wait: float = 2.0
    retry_max_wait: float = 60.0

    # Data Pipeline Configuration
    # Backfill window when discovering new traders (months)
    backfill_months: int = 12
    # Categories to store full trade detail (others stored as aggregates)
    # Config-driven, not hardcoded - supports any category
    detail_categories: List[str] = ["eSports"]

    # Logging Configuration
    log_level: str = "INFO"
    log_dir: str = "logs"

    # Pydantic v2 configuration
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
    )


@lru_cache
def get_settings() -> Settings:
    """Get cached settings instance.

    Uses lru_cache to ensure settings are loaded only once and reused
    across the application.

    Returns:
        Settings instance with loaded configuration
    """
    return Settings()
