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
    # Reasoning ("thinking") for models that have it (Qwen3, Qwen3.5...). Off by default: labelling
    # and filter-reading do not need it and on a CPU it multiplies the time. A call that really
    # needs it asks for it explicitly (see app.services.ollama.generate); True turns it on for all.
    ollama_think: bool = False

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

    # Optional HMAC key for account fingerprints. If empty, a random key is generated
    # once and kept in the settings table.
    account_fingerprint_key: str = ""

    # AI fallback for transactions the rules cannot categorise (local Ollama only).
    llm_classify_enabled: bool = True
    # Only suggestions at or above this confidence are applied; the rest go to review.
    llm_confidence_threshold: float = 0.8
    # Between this and the threshold the guess is kept only as a hint in Review (not applied).
    llm_hint_threshold: float = 0.4
    # The Suggestions tab offers "accept all" for suggestions at or above this confidence.
    llm_confident_threshold: float = 0.9
    # Your own confirmed descriptions, shown to the model as examples (descriptions only).
    llm_example_limit: int = 12
    # Also tell the model whether money came in or went out and a coarse size band
    # (small/medium/large). Off by default: with it off only description text is sent.
    llm_amount_hints: bool = False

    # Similarity hints (docs/08, 4.3): suggest a category from descriptions you already
    # categorised, using a small local embedding model. OFF until you have measured it on your own
    # data: pull the model, run `python -m app.tools.eval_embeddings`, then set EMBED_SUGGEST_ENABLED.
    embed_enabled: bool = False
    ollama_embed_model: str = "nomic-embed-text"
    # nomic-embed-text expects a task word before each text ("classification: ..."). Without it
    # unrelated short strings score close together. Empty: send the text as it is.
    embed_task: str = "classification"
    embed_min_neighbours: int = 2  # how many close, agreeing neighbours a hint needs
    embed_k: int = 5  # nearest labelled descriptions consulted
    embed_min_similarity: float = 0.80  # neighbours less similar than this are ignored
    embed_min_agree: float = 0.80  # share of the neighbours that must agree
    embed_min_labelled: int = 20  # fewer corrected descriptions than this: do not suggest

    # Job queue / worker.
    job_poll_s: float = 2.0
    job_timeout_s: float = 120.0
    job_max_attempts: int = 3
    job_stale_after_s: int = 600


@lru_cache
def get_settings() -> Settings:
    return Settings()
