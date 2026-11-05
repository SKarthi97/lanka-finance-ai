import time

import httpx

from app.config import Settings


# Models that answered "does not support thinking" once; they are not sent the option again.
_NO_THINK_SUPPORT: set[str] = set()


def generate_body(
    settings: Settings,
    prompt: str,
    *,
    schema: dict | None = None,
    think: bool | None = None,
    options: dict | None = None,
) -> dict:
    """The JSON body for POST /api/generate.

    `think` is explicit reasoning for models that have it: None uses the OLLAMA_THINK setting
    (off unless you turned it on), True asks this call to reason, False forbids it. It is only
    sent to models that accept it.
    """
    body: dict = {
        "model": settings.ollama_model,
        "prompt": prompt,
        "stream": False,
        "options": {"temperature": 0, **(options or {})},
    }
    if schema is not None:
        body["format"] = schema
    if settings.ollama_model not in _NO_THINK_SUPPORT:
        body["think"] = settings.ollama_think if think is None else think
    return body


def generate(
    client: httpx.Client,
    settings: Settings,
    prompt: str,
    *,
    schema: dict | None = None,
    think: bool | None = None,
    options: dict | None = None,
) -> httpx.Response:
    """POST /api/generate, retrying once without `think` if the model rejects the option
    (a model with no reasoning mode, or an older Ollama). The caller checks the status."""
    body = generate_body(settings, prompt, schema=schema, think=think, options=options)
    reply = client.post("/api/generate", json=body)
    if reply.status_code == 400 and "think" in body and "think" in reply.text.lower():
        _NO_THINK_SUPPORT.add(settings.ollama_model)
        body.pop("think")
        reply = client.post("/api/generate", json=body)
    return reply


async def check_ollama(
    settings: Settings,
    warmup: bool = False,
    transport: httpx.AsyncBaseTransport | None = None,
) -> dict:
    """Report whether Ollama is reachable and the configured model is present.

    With warmup=True, also runs a one-token inference to load the model.
    The backend never calls anything but the configured Ollama URL.
    """
    result: dict = {
        "reachable": False,
        "model": settings.ollama_model,
        "model_present": False,
        "digest": None,
        "installed_models": [],
        "warmup_ok": None,
        "warmup_ms": None,
        "error": None,
    }

    async with httpx.AsyncClient(
        base_url=settings.ollama_base_url,
        timeout=settings.ollama_timeout_s,
        transport=transport,
    ) as client:
        try:
            tags = await client.get("/api/tags")
            tags.raise_for_status()
        except httpx.HTTPError as error:
            result["error"] = f"Ollama unreachable: {type(error).__name__}"
            return result

        result["reachable"] = True
        models = tags.json().get("models", [])
        result["installed_models"] = [m.get("name", "") for m in models]

        wanted = settings.ollama_model
        for entry in models:
            name = entry.get("name", "")
            if name == wanted or (":" not in wanted and name.split(":")[0] == wanted):
                result["model_present"] = True
                result["digest"] = entry.get("digest")
                break

        if not result["model_present"]:
            result["error"] = (
                f"Model '{wanted}' is not installed. Run: docker compose up ollama-pull"
            )
            return result

        if warmup:
            started = time.perf_counter()
            try:
                reply = await client.post(
                    "/api/generate",
                    json={
                        "model": wanted,
                        "prompt": "ping",
                        "stream": False,
                        "options": {"num_predict": 1},
                    },
                )
                reply.raise_for_status()
                result["warmup_ok"] = True
            except httpx.HTTPError as error:
                result["warmup_ok"] = False
                result["error"] = f"Warm-up failed: {type(error).__name__}"
            result["warmup_ms"] = int((time.perf_counter() - started) * 1000)

    return result
