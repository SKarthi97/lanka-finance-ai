"""Reasoning ("thinking") is off unless asked for. Against a fake Ollama."""

import json

import httpx
import pytest

from app.config import Settings
from app.services import merchants, ollama

from .test_ai_features import fake_ollama, loaded  # noqa: F401  (the fixture)


@pytest.fixture(autouse=True)
def forget_unsupported():
    ollama._NO_THINK_SUPPORT.clear()
    yield
    ollama._NO_THINK_SUPPORT.clear()


def test_thinking_is_off_by_default():
    assert Settings().ollama_think is False
    body = ollama.generate_body(Settings(), "hello", schema={"type": "object"})
    assert body["think"] is False
    assert body["format"] == {"type": "object"}
    assert body["options"]["temperature"] == 0


def test_the_setting_turns_it_on_for_every_call():
    assert ollama.generate_body(Settings(ollama_think=True), "x")["think"] is True


def test_one_call_can_ask_for_reasoning_or_forbid_it():
    off, on = Settings(), Settings(ollama_think=True)
    assert ollama.generate_body(off, "x", think=True)["think"] is True
    assert ollama.generate_body(on, "x", think=False)["think"] is False


def test_the_app_features_send_think_false(loaded, session_factory, test_settings):  # noqa: F811
    seen: list = []
    with session_factory() as db:
        merchants.propose(db, test_settings, ["KEELLS SUPER"], [], fake_ollama([{"results": []}], seen))
    assert seen[0]["think"] is False


def test_the_setting_reaches_the_features(loaded, session_factory, test_settings):  # noqa: F811
    test_settings.ollama_think = True
    seen: list = []
    with session_factory() as db:
        merchants.propose(db, test_settings, ["KEELLS SUPER"], [], fake_ollama([{"results": []}], seen))
    assert seen[0]["think"] is True


def rejecting_ollama(seen):
    """A model with no reasoning mode: it answers 400 whenever `think` is present."""

    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        seen.append(body)
        if "think" in body:
            return httpx.Response(400, json={"error": '"qwen2.5:1.5b" does not support thinking'})
        return httpx.Response(200, json={"response": "{}"})

    return httpx.MockTransport(handler)


def test_a_model_without_reasoning_is_retried_without_the_option_and_remembered():
    settings = Settings()
    seen: list = []
    with httpx.Client(base_url="http://ollama", transport=rejecting_ollama(seen)) as client:
        first = ollama.generate(client, settings, "x")
        assert first.status_code == 200
        assert ["think" in b for b in seen] == [True, False]  # tried, then retried without

        ollama.generate(client, settings, "y")
        assert ["think" in b for b in seen] == [True, False, False]  # remembered: not sent again


def test_other_400_errors_are_not_swallowed():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(400, json={"error": "invalid format schema"})

    with httpx.Client(base_url="http://ollama", transport=httpx.MockTransport(handler)) as client:
        assert ollama.generate(client, Settings(), "x").status_code == 400
        assert ollama._NO_THINK_SUPPORT == set()
