from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Runtime configuration. Every field can be set via an environment variable
    of the same name (case-insensitive), e.g. OLLAMA_MODEL."""

    model_config = SettingsConfigDict(extra="ignore")

    database_url: str = "postgresql+psycopg://lanka:lanka@postgres:5432/lanka"

    ollama_base_url: str = "http://ollama:11434"
    ollama_model: str = "qwen2.5:1.5b"
    ollama_timeout_s: float = 60.0

    cookie_name: str = "lanka_session"
    # Set true when the frontend is served over HTTPS.
    cookie_secure: bool = False
    session_ttl_hours: int = 12

    login_max_attempts: int = 5
    login_window_s: int = 300

    min_password_length: int = 12


@lru_cache
def get_settings() -> Settings:
    return Settings()
