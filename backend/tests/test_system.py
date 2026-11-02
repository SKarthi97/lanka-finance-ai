import asyncio

import httpx
import pytest

from app.config import Settings
from app.services.hardware import recommend_model
from app.services.ollama import check_ollama


def test_health_is_public(client):
    response = client.get("/api/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok", "database": True}


def test_hardware_report_shape(logged_in):
    client, _ = logged_in
    body = client.get("/api/system/hardware").json()
    for key in ("cpu_threads", "ram_total_gb", "ram_available_gb", "gpu", "recommended_model_size"):
        assert key in body


@pytest.mark.parametrize(
    "free_gb, gpu, expected",
    [
        (4, False, "1.7-3B"),
        (9.9, False, "1.7-3B"),
        (10, False, "4B"),
        (22, False, "4B"),
        (24, False, "8B"),
        (4, True, "8B"),
    ],
)
def test_recommend_model(free_gb, gpu, expected):
    assert recommend_model(free_gb, gpu) == expected


def _ollama(handler, warmup=False, model="qwen2.5:1.5b"):
    settings = Settings(ollama_model=model, ollama_base_url="http://ollama:11434")
    return asyncio.run(
        check_ollama(settings, warmup=warmup, transport=httpx.MockTransport(handler))
    )


def test_ollama_unreachable():
    def handler(request):
        raise httpx.ConnectError("refused")

    result = _ollama(handler)
    assert result["reachable"] is False
    assert "unreachable" in result["error"]


def test_ollama_model_missing():
    def handler(request):
        return httpx.Response(200, json={"models": [{"name": "llama3:8b"}]})

    result = _ollama(handler)
    assert result["reachable"] is True
    assert result["model_present"] is False
    assert "ollama-pull" in result["error"]


def test_ollama_model_present_with_digest_and_warmup():
    def handler(request):
        if request.url.path == "/api/tags":
            return httpx.Response(
                200, json={"models": [{"name": "qwen2.5:1.5b", "digest": "abc123"}]}
            )
        assert request.url.path == "/api/generate"
        return httpx.Response(200, json={"response": "p"})

    result = _ollama(handler, warmup=True)
    assert result["model_present"] is True
    assert result["digest"] == "abc123"
    assert result["warmup_ok"] is True
    assert result["error"] is None
