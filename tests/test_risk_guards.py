"""Risk guard tests: daily-loss halt, max-position cap, paper assertion."""

from __future__ import annotations

import pytest

from config.settings import Settings
from src.risk.guards import (
    AccountSnapshot,
    assert_paper,
    check_entry_allowed,
    daily_loss_pct,
)


def _snap(**kw) -> AccountSnapshot:
    base = {
        "equity": 200.0,
        "last_equity": 200.0,
        "cash": 200.0,
        "open_positions": 0,
        "is_paper": True,
    }
    base.update(kw)
    return AccountSnapshot(**base)


def test_entry_allowed_baseline(settings):
    result = check_entry_allowed(settings, _snap(), prospective_notional=25.0)
    assert result.allowed is True


def test_daily_loss_halt(settings):
    # Equity down 12% from last close -> exceeds the 10% halt threshold.
    snap = _snap(equity=176.0, last_equity=200.0)
    result = check_entry_allowed(settings, snap, prospective_notional=25.0)
    assert result.allowed is False
    assert "daily_loss_halt" in result.reason


def test_daily_loss_pct_math():
    assert daily_loss_pct(_snap(equity=180.0, last_equity=200.0)) == pytest.approx(-10.0)
    assert daily_loss_pct(_snap(equity=200.0, last_equity=0.0)) == 0.0


def test_max_positions_cap(settings):
    snap = _snap(open_positions=8)  # at the cap of 8
    result = check_entry_allowed(settings, snap, prospective_notional=25.0)
    assert result.allowed is False
    assert "max_positions" in result.reason


def test_single_position_equity_cap(settings):
    # 20% of $200 = $40 cap; a $50 order must be rejected.
    result = check_entry_allowed(settings, _snap(), prospective_notional=50.0)
    assert result.allowed is False
    assert "position_over_equity_cap" in result.reason


def test_insufficient_cash_guard(settings):
    snap = _snap(cash=10.0)
    result = check_entry_allowed(settings, snap, prospective_notional=25.0)
    assert result.allowed is False
    assert "insufficient_cash" in result.reason


def test_paper_assertion_blocks_non_paper():
    # Not paper and live not enabled -> hard fail.
    with pytest.raises(RuntimeError):
        assert_paper(is_paper=False, live_enabled=False)
    # Paper is always fine.
    assert_paper(is_paper=True, live_enabled=False)
    # Non-paper allowed only when live is explicitly enabled.
    assert_paper(is_paper=False, live_enabled=True)


def test_guard_blocks_entry_on_non_paper(settings):
    snap = _snap(is_paper=False)
    result = check_entry_allowed(settings, snap, prospective_notional=25.0)
    assert result.allowed is False
    assert result.reason == "not_paper"


def test_settings_paper_gate():
    # Live endpoint without gates open must refuse.
    s = Settings(alpaca_base_url="https://api.alpaca.markets", allow_live=False, confirm_live=False)
    assert s.is_paper is False
    with pytest.raises(RuntimeError):
        s.assert_paper_or_live_ok()
    # Both gates open -> allowed.
    s2 = Settings(alpaca_base_url="https://api.alpaca.markets", allow_live=True, confirm_live=True)
    assert s2.live_enabled is True
    s2.assert_paper_or_live_ok()  # no raise
