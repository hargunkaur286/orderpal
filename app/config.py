from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Reads from environment variables, falling back to .env. Types are validated at startup,
    so a typo'd URL fails fast instead of at the first request."""

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str = "postgresql://orderpal:orderpal@localhost:5433/orderpal"
    redis_url: str = "redis://localhost:6380/0"
    embedding_model: str = "BAAI/bge-small-en-v1.5"
    llm_model: str = "gemini-3.5-flash-lite"
    llm_fallback_model: str = "gemini-3.1-flash-lite"   # used when the primary errors or times out
    gemini_api_key: str = ""

    # Cost tracking. Fill these from the provider's pricing page; 0 = only tokens are reported.
    llm_price_input_usd_per_m: float = 0.0     # USD per 1M input tokens
    llm_price_output_usd_per_m: float = 0.0    # USD per 1M output tokens
    usd_to_inr: float = 0.0

    rate_limit_per_minute: int = 10            # LLM-backed requests per user (or IP) per minute


@lru_cache
def get_settings() -> Settings:
    return Settings()
