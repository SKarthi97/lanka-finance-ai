"""One schema-constrained question to the local model, with the bookkeeping every caller needs.

Shared by merchant naming and search interpretation. The reply must be JSON that matches a
schema and validates against a Pydantic model; anything else counts as "no answer", never as a
guess. Each call is recorded in `model_runs` with a hash of the prompt, never its text.
"""

import hashlib
import json
import time
from typing import TypeVar

import httpx
from pydantic import BaseModel, ValidationError
from sqlalchemy.orm import Session

from app.config import Settings
from app.models import ModelRun
from app.services import ollama
from app.services.llm_classifier import LlmUnavailable, _model_digest

T = TypeVar("T", bound=BaseModel)

ATTEMPTS = 2


def open_client(settings: Settings, transport: httpx.BaseTransport | None = None) -> httpx.Client:
    return httpx.Client(
        base_url=settings.ollama_base_url, timeout=settings.ollama_timeout_s, transport=transport
    )


def digest_or_raise(client: httpx.Client, settings: Settings) -> str | None:
    """The installed model's digest; LlmUnavailable when Ollama or the model is missing."""
    try:
        return _model_digest(client, settings.ollama_model)
    except httpx.HTTPError as error:
        raise LlmUnavailable(f"Ollama unreachable: {type(error).__name__}") from None


def ask(
    db: Session,
    settings: Settings,
    client: httpx.Client,
    digest: str | None,
    purpose: str,
    prompt: str,
    schema: dict,
    model: type[T],
    think: bool | None = None,
) -> T | None:
    """Ask once (retrying an unusable reply). None when no valid reply came.

    `think=True` lets the model reason for this question; the default follows OLLAMA_THINK
    (off). Nothing in the app needs reasoning today: labelling and filter-reading are lookups.
    """
    prompt_hash = hashlib.sha256(prompt.encode()).hexdigest()
    for _ in range(ATTEMPTS):
        began = time.perf_counter()
        parsed: T | None = None
        try:
            reply = ollama.generate(client, settings, prompt, schema=schema, think=think)
            reply.raise_for_status()
            parsed = model.model_validate(json.loads(reply.json().get("response", "")))
        except (httpx.HTTPError, ValueError, ValidationError):
            parsed = None
        db.add(
            ModelRun(
                model=settings.ollama_model,
                digest=digest,
                purpose=purpose,
                prompt_hash=prompt_hash,
                duration_ms=int((time.perf_counter() - began) * 1000),
                valid_json=parsed is not None,
            )
        )
        if parsed is not None:
            return parsed
    return None
