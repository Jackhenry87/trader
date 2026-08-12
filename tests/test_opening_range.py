"""ORB: mechanics, and behaviour on sessions whose outcome is known by design.

*Mechanics* pin the anti-bias properties — the breakout fills on the bar after
the signal, the entry bar can stop out, costs are charged, shorts are
sign-corrected, nothing survives the close.

*Ground truth* runs sessions built to trend, to whipsaw, or to go nowhere, and
checks the strategy profits, loses, and stays flat respectively. That validates
the implementation. It says nothing about real markets.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from backtest.opening_range import (
    ORBParams,
    max_day_trades_in_window,
    opening_range,
    run_orb,
    session_days,
    simulate_session,
)

OPEN = "2024-05-01 13:30"  # RTH open in UTC


def bars_from_closes(closes, day="2024-05-01", freq_min=5):
    """OHLC from closes, open[i]=close[i-1], tight intraday range."""
    closes = [float(c) for c in closes]
    opens = [closes[0]] + closes[:-1]
    idx = pd.date_range(f"{day} 13:30", periods=len(closes), freq=f"{freq_min}min")
    return pd.DataFrame(
        {
            "open": opens,
            "high": [max(o, c) * 1.001 for o, c in zip(opens, closes, strict=True)],
            "low": [min(o, c) * 0.999 for o, c in zip(opens, closes, strict=True)],
            "close": closes,
        },
        index=idx,
    )


def trending_session(day, up=True):
    """Chop for the range, then break out and run in one direction."""
    base = [100.0, 100.5, 99.8, 100.2]  # 20 min of range on 5-min bars
    move = np.linspace(101.0, 112.0, 20) if up else np.linspace(99.0, 88.0, 20)
    return bars_from_closes(base + list(move), day=day)


def whipsaw_session(day):
    """Breaks above the range, then collapses straight back through the low."""
    base = [100.0, 100.5, 99.8, 100.2]
    fake = [101.2, 101.5]  # pops above the range high
    fail = list(np.linspace(100.0, 94.0, 14))  # then dies
    return bars_from_closes(base + fake + fail, day=day)


def flat_session(day):
    return bars_from_closes([100.0] * 24, day=day)


# ── Mechanics ────────────────────────────────────────────────────────────────


def test_opening_range_uses_only_the_first_n_minutes():
    bars = bars_from_closes([100.0, 105.0, 95.0, 100.0, 200.0, 50.0])  # 5-min bars
    hi, lo, after = opening_range(bars, range_minutes=15)  # first 3 bars
    assert hi == pytest.approx(105.0 * 1.001)
    assert lo == pytest.approx(95.0 * 0.999)
    # The 200/50 bars are after the range and must not widen it.
    assert len(after) == 3


def test_range_returns_none_when_session_too_short():
    assert opening_range(bars_from_closes([100.0, 101.0]), range_minutes=15) is None
    assert opening_range(pd.DataFrame(), range_minutes=15) is None


def test_entry_fills_on_the_bar_after_the_breakout():
    """The core anti-bias property: no fill at the breakout level itself."""
    bars = trending_session("2024-05-01")
    t = simulate_session("X", bars, ORBParams(range_minutes=20, direction="long"))
    assert t is not None

    hi, _lo, after = opening_range(bars, 20)
    signal_idx = next(i for i in range(len(after)) if float(after.iloc[i]["high"]) > hi)
    signal_ts = after.index[signal_idx]
    fill_ts = after.index[signal_idx + 1]

    assert pd.Timestamp(t.entry_date) == fill_ts, "must fill on the bar AFTER the signal"
    assert pd.Timestamp(t.entry_date) > signal_ts
    assert t.entry_price == pytest.approx(float(after.iloc[signal_idx + 1]["open"]))


def test_entry_bar_can_stop_out():
    """A breakout that fails instantly must not get a free bar."""
    bars = whipsaw_session("2024-05-01")
    t = simulate_session("X", bars, ORBParams(range_minutes=20, direction="long"))
    assert t is not None
    assert t.trigger == "long_stop"
    assert t.return_pct < 0


def test_position_is_always_closed_by_session_end():
    bars = trending_session("2024-05-01")
    t = simulate_session("X", bars, ORBParams(range_minutes=20, direction="long"))
    assert t is not None
    assert pd.Timestamp(t.exit_date) <= bars.index[-1]
    assert t.trigger.endswith(("stop", "target", "session_close"))


def test_costs_are_charged_both_sides():
    bars = trending_session("2024-05-01")
    free = ORBParams(range_minutes=20, commission_pct=0.0, slippage_pct=0.0)
    paid = ORBParams(range_minutes=20, commission_pct=0.1, slippage_pct=0.05)
    assert paid.round_trip_cost_pct == pytest.approx(0.30)
    g = simulate_session("X", bars, free).return_pct
    n = simulate_session("X", bars, paid).return_pct
    assert n == pytest.approx(g - 0.30, abs=0.01)


def test_short_pnl_is_sign_corrected():
    """A short into a falling market must be a WIN, not a loss."""
    bars = trending_session("2024-05-01", up=False)
    t = simulate_session("X", bars, ORBParams(range_minutes=20, direction="short"))
    assert t is not None
    assert t.trigger.startswith("short_")
    assert t.return_pct > 0, "short in a downtrend should profit"


def test_flat_session_produces_no_trade():
    assert simulate_session("X", flat_session("2024-05-01"), ORBParams(range_minutes=20)) is None


def test_long_only_ignores_downside_breaks():
    bars = trending_session("2024-05-01", up=False)
    assert simulate_session("X", bars, ORBParams(range_minutes=20, direction="long")) is None


def test_target_exit_fires():
    bars = trending_session("2024-05-01")
    t = simulate_session("X", bars, ORBParams(range_minutes=20, direction="long", target_r=1.0))
    assert t is not None and t.trigger == "long_target"


def test_rejects_bad_params():
    with pytest.raises(ValueError, match="direction"):
        run_orb({}, ORBParams(direction="sideways"))
    with pytest.raises(ValueError, match="range_minutes"):
        run_orb({}, ORBParams(range_minutes=0))


def test_sessions_are_split_by_date():
    a = trending_session("2024-05-01")
    b = trending_session("2024-05-02")
    days = session_days(pd.concat([a, b]))
    assert len(days) == 2


# ── Ground truth ─────────────────────────────────────────────────────────────


def test_profits_on_sessions_that_trend_after_the_open():
    frames = {"T": pd.concat([trending_session(f"2024-05-{d:02d}") for d in range(1, 11)])}
    _, m = run_orb(frames, ORBParams(range_minutes=20, direction="long"))
    assert m["trades"] == 10
    assert m["expectancy_pct"] > 0
    assert m["win_rate_pct"] == 100.0


def test_loses_on_sessions_that_whipsaw():
    frames = {"W": pd.concat([whipsaw_session(f"2024-05-{d:02d}") for d in range(1, 11)])}
    _, m = run_orb(frames, ORBParams(range_minutes=20, direction="long"))
    assert m["trades"] == 10
    assert m["expectancy_pct"] < 0
    assert set(m["exits_by_trigger"]) == {"long_stop"}


def test_flat_market_generates_nothing():
    frames = {"F": pd.concat([flat_session(f"2024-05-{d:02d}") for d in range(1, 11)])}
    trades, m = run_orb(frames, ORBParams(range_minutes=20))
    assert trades == []
    assert m["trades"] == 0


# ── PDT ──────────────────────────────────────────────────────────────────────


def test_pdt_counter_finds_the_worst_rolling_window():
    from datetime import date as d

    assert max_day_trades_in_window([]) == 0
    # Mon-Wed, three consecutive business days -> 3 in one window.
    assert max_day_trades_in_window([d(2024, 5, 6), d(2024, 5, 7), d(2024, 5, 8)]) == 3
    # Spread across three weeks -> never more than 1 in any 5-business-day window.
    assert max_day_trades_in_window([d(2024, 5, 6), d(2024, 5, 20), d(2024, 6, 3)]) == 1


def test_pdt_warning_appears_when_the_limit_is_exceeded():
    """Daily trading trips the rule; the metrics must say so."""
    frames = {"T": pd.concat([trending_session(f"2024-05-{d:02d}") for d in range(1, 11)])}
    _, m = run_orb(frames, ORBParams(range_minutes=20, direction="long"))
    assert m["day_trades"] == 10
    assert m["max_day_trades_in_5d"] > 3
    assert "pdt_warning" in m
    assert "not tradeable" in m["pdt_warning"]


def test_no_pdt_warning_when_trades_are_sparse():
    """One trade every couple of weeks stays inside the limit."""
    frames = {
        "T": pd.concat([trending_session(d) for d in ("2024-05-01", "2024-05-20", "2024-06-10")])
    }
    _, m = run_orb(frames, ORBParams(range_minutes=20, direction="long"))
    assert m["max_day_trades_in_5d"] == 1
    assert "pdt_warning" not in m
