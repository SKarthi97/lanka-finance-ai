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
