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

    # Uploaded statements live on a Docker named volume shared with the worker.
    documents_dir: str = "/data/documents"
    max_upload_mb: int = 25
    max_pages: int = 300
    # False: the stored PDF is deleted once processing succeeds (the sha256 stays in
    # the database, so duplicate detection still works). Failed documents always keep
    # their file so they can be retried. Set true to keep every statement file.
    retain_documents: bool = False

    # Job queue / worker.
    job_poll_s: float = 2.0
    job_timeout_s: float = 120.0
    job_max_attempts: int = 3
    job_stale_after_s: int = 600


@lru_cache
def get_settings() -> Settings:
    return Settings()
