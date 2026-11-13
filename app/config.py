from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Reads from environment variables, falling back to .env. Types are validated at startup,
    so a typo'd URL fails fast instead of at the first request."""

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str = "postgresql://orderpal:orderpal@localhost:5433/orderpal"
    redis_url: str = "redis://localhost:6380/0"
    embedding_model: str = "BAAI/bge-small-en-v1.5"


@lru_cache
def get_settings() -> Settings:
    return Settings()
