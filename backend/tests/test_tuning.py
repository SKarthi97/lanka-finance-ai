import importlib
from decimal import Decimal

import pytest

from app import tuning


def test_defaults_are_the_documented_numbers():
    assert tuning.IDLE_MIN_BALANCE == Decimal("25000") and tuning.IDLE_NO_INTEREST_DAYS == 180
    assert tuning.DROP_POINTS == Decimal("0.50") and tuning.STALE_DAYS == 45


def test_a_setting_in_the_environment_changes_a_threshold(monkeypatch):
    monkeypatch.setenv("TUNE_IDLE_MIN_BALANCE", "50000")
    monkeypatch.setenv("TUNE_STALE_DAYS", "30")
    try:
        reloaded = importlib.reload(tuning)
        assert reloaded.IDLE_MIN_BALANCE == Decimal("50000") and reloaded.STALE_DAYS == 30
    finally:
        monkeypatch.undo()
        importlib.reload(tuning)


def test_an_unreadable_value_stops_start_up(monkeypatch):
    monkeypatch.setenv("TUNE_STALE_DAYS", "soon")
    try:
        with pytest.raises(ValueError, match="TUNE_STALE_DAYS"):
            importlib.reload(tuning)
    finally:
        monkeypatch.undo()
        importlib.reload(tuning)


def test_the_documented_similarity_switch_reaches_the_settings(monkeypatch):
    from app.config import Settings

    assert Settings().embed_enabled is False
    monkeypatch.setenv("EMBED_SUGGEST_ENABLED", "true")
    assert Settings().embed_enabled is True
    monkeypatch.delenv("EMBED_SUGGEST_ENABLED")
    monkeypatch.setenv("EMBED_ENABLED", "true")
    assert Settings().embed_enabled is True
    assert Settings(embed_enabled=True).embed_enabled is True  # tests and code can still pass it by name


def test_the_remaining_ai_settings_are_forwarded_by_compose():
    import re
    from pathlib import Path

    compose = (Path(__file__).resolve().parents[2] / "docker-compose.yml").read_text(encoding="utf-8")
    for name in ("LLM_HINT_THRESHOLD", "LLM_CONFIDENT_THRESHOLD", "LLM_EXAMPLE_LIMIT", "LLM_AMOUNT_HINTS", "EMBED_MIN_LABELLED"):
        assert len(re.findall(rf"^\s+{name}:", compose, re.M)) == 2, name  # backend and worker
