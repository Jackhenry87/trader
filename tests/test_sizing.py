"""Sizing tests: notional sizing and equity-percentage cap."""

from __future__ import annotations

from config.settings import Settings
from src.execution.sizing import size_position


def test_basic_notional(settings):
    d = size_position(settings, equity=200.0, available_cash=200.0)
    assert d.approved is True
    assert d.notional == 25.0  # dollars_per_position


def test_equity_cap_limits_notional():
    # 20% of $100 equity = $20 cap, below the $25 base -> clamp to $20.
    s = Settings(dollars_per_position=25.0, max_position_equity_pct=20.0)
    d = size_position(s, equity=100.0, available_cash=1000.0)
    assert d.approved is True
    assert d.notional == 20.0


def test_limited_by_available_cash(settings):
    d = size_position(settings, equity=200.0, available_cash=10.0)
    assert d.approved is True
    assert d.notional == 10.0


def test_insufficient_cash_rejected(settings):
    d = size_position(settings, equity=200.0, available_cash=0.5)
    assert d.approved is False
    assert d.reason == "insufficient_cash"


def test_non_positive_equity_rejected(settings):
    d = size_position(settings, equity=0.0, available_cash=100.0)
    assert d.approved is False
    assert d.reason == "non_positive_equity"


def test_below_min_notional_rejected():
    # A tiny equity cap can push the size below Alpaca's $1 notional minimum.
    s = Settings(dollars_per_position=25.0, max_position_equity_pct=1.0)
    d = size_position(s, equity=50.0, available_cash=1000.0)  # cap = $0.50
    assert d.approved is False
    assert d.reason == "below_min_notional"
