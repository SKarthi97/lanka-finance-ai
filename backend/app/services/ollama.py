import time

import httpx

from app.config import Settings


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
