"""Exit manager tests: trailing stop, hard stop, max hold, HWM tracking."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from src.execution.exit import evaluate_exit
from src.state.repo import PositionRow


def _pos(entry=100.0, hwm=100.0, days_ago=0) -> PositionRow:
    entry_at = (datetime.now(UTC) - timedelta(days=days_ago)).isoformat()
    return PositionRow(
        ticker="TST",
        entry_price=entry,
        qty=1.0,
        entry_at=entry_at,
        high_water_mark=hwm,
        status="open",
    )


def test_hard_stop_triggers(settings):
    # entry 100, hard stop 15% -> exit at/below 85.
    d = evaluate_exit(_pos(entry=100.0, hwm=100.0), current_price=84.0, settings=settings)
    assert d.should_exit is True
    assert d.trigger == "hard_stop"


def test_trailing_stop_triggers(settings):
    # HWM 120, trail 10% -> stop at 108. Price 107 exits.
    d = evaluate_exit(_pos(entry=100.0, hwm=120.0), current_price=107.0, settings=settings)
    assert d.should_exit is True
    assert d.trigger == "trailing_stop"


def test_no_exit_when_above_stops(settings):
    d = evaluate_exit(_pos(entry=100.0, hwm=120.0), current_price=115.0, settings=settings)
    assert d.should_exit is False
    assert d.trigger is None


def test_high_water_mark_advances(settings):
    d = evaluate_exit(_pos(entry=100.0, hwm=100.0), current_price=130.0, settings=settings)
    assert d.new_high_water_mark == 130.0
    assert d.should_exit is False


def test_max_hold_forces_exit(settings):
    # Held 25 days > max_hold_days 20, price fine.
    d = evaluate_exit(
        _pos(entry=100.0, hwm=100.0, days_ago=25), current_price=101.0, settings=settings
    )
    assert d.should_exit is True
    assert d.trigger == "max_hold"


def test_hard_stop_takes_precedence_over_trailing(settings):
    # Price below both hard stop (85) and trail. Hard stop wins.
    d = evaluate_exit(_pos(entry=100.0, hwm=120.0), current_price=80.0, settings=settings)
    assert d.trigger == "hard_stop"
