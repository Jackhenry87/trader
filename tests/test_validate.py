"""Validation battery: the tests that decide whether a backtest is believed."""

from __future__ import annotations

import pytest

from backtest.run_backtest import TradeRecord
from backtest.validate import (
    by_regime,
    cost_sensitivity,
    format_validation,
    independence,
    split_sample,
    trade_stats,
    validate,
)


def tr(ticker: str, entry: str, ret: float) -> TradeRecord:
    return TradeRecord(
        ticker=ticker,
        entry_date=entry,
        entry_price=100.0,
        exit_date=entry,
        exit_price=100.0 * (1 + ret / 100),
        hold_days=1,
        return_pct=ret,
        trigger="test",
    )


# ── Core stats ───────────────────────────────────────────────────────────────


def test_expectancy_exposes_a_winning_looking_loser():
    """3 small wins, 1 big loss: 75% win rate, negative expectancy."""
    t = [
        tr("A", "2024-01-01", 1.0),
        tr("B", "2024-01-02", 1.0),
        tr("C", "2024-01-03", 1.0),
        tr("D", "2024-01-04", -6.0),
    ]
    s = trade_stats(t)
    assert s["win_rate_pct"] == 75.0
    assert s["expectancy_pct"] == pytest.approx(-0.75)
    assert s["profit_factor"] < 1
    assert "losers outweigh winners" in format_validation(validate(t))


def test_empty_input_is_handled_everywhere():
    assert trade_stats([]) == {"trades": 0}
    assert independence([]) == {"trades": 0}
    assert split_sample([])["train"]["trades"] == 0
    assert "no trades" in format_validation(validate([]))


def test_profit_factor_none_without_losses():
    assert trade_stats([tr("A", "2024-01-01", 5.0)])["profit_factor"] is None


# ── Split ────────────────────────────────────────────────────────────────────


def test_split_is_chronological_not_random():
    """Trades must be partitioned by date, regardless of input order."""
    t = [
        tr("A", "2024-06-01", 5.0),
        tr("B", "2024-01-01", -5.0),
        tr("C", "2024-12-01", 5.0),
        tr("D", "2024-02-01", -5.0),
    ]
    sp = split_sample(t, cutoff="2024-05-01")
    assert sp["train"]["trades"] == 2  # Jan + Feb
    assert sp["test"]["trades"] == 2  # Jun + Dec
    assert sp["train"]["expectancy_pct"] < 0 < sp["test"]["expectancy_pct"]


def test_split_flags_a_regime_dependent_strategy_as_failing():
    """Positive overall, negative in the first half -> must FAIL."""
    t = [tr("A", f"2024-0{m}-01", -2.0) for m in range(1, 5)]
    t += [tr("B", f"2024-0{m}-01", 6.0) for m in range(5, 9)]
    sp = split_sample(t, cutoff="2024-05-01")
    assert trade_stats(t)["expectancy_pct"] > 0, "positive overall"
    assert sp["consistent"] is False
    assert "FAILS" in format_validation(validate(t, cutoff="2024-05-01"))


def test_split_passes_a_consistently_positive_strategy():
    t = [tr("A", f"2024-0{m}-01", 2.0) for m in range(1, 9)]
    sp = split_sample(t, cutoff="2024-05-01")
    assert sp["consistent"] is True
    assert "consistent across both halves" in format_validation(validate(t, cutoff="2024-05-01"))


def test_split_defaults_to_median_entry_date():
    t = [tr("A", f"2024-0{m}-01", 1.0) for m in range(1, 5)]
    sp = split_sample(t)
    assert sp["cutoff"] is not None
    assert sp["train"]["trades"] + sp["test"]["trades"] == 4


# ── Regimes ──────────────────────────────────────────────────────────────────


def test_regime_breakdown_partitions_by_entry_date():
    t = [tr("A", "2020-03-15", -10.0), tr("B", "2024-05-01", 3.0)]
    r = by_regime(t)
    assert r["COVID crash 2020"]["trades"] == 1
    assert r["COVID crash 2020"]["expectancy_pct"] == pytest.approx(-10.0)
    assert r["2023+ recovery"]["trades"] == 1
    assert r["2018 Q4 selloff"]["trades"] == 0


def test_empty_regimes_are_reported_not_dropped():
    out = format_validation(validate([tr("A", "2024-05-01", 1.0)]))
    assert "no trades in period" in out


def test_negative_regimes_are_named():
    t = [tr("A", "2020-03-15", -10.0), tr("B", "2024-05-01", 3.0)]
    out = format_validation(validate(t))
    assert "Negative in: COVID crash 2020" in out


# ── Independence ─────────────────────────────────────────────────────────────


def test_independence_detects_clustered_entries():
    """Four tickers all entering the same day is one bet, not four."""
    t = [tr(c, "2024-03-01", 1.0) for c in "ABCD"]
    ind = independence(t)
    assert ind["distinct_entry_dates"] == 1
    assert ind["shared_pct"] == 100.0
    assert ind["worst_day_simultaneous"] == 4
    assert ind["effective_sample_estimate"] == 1
    assert "heavily clustered" in format_validation(validate(t))


def test_independence_is_quiet_when_entries_are_spread():
    t = [tr("A", f"2024-0{m}-01", 1.0) for m in range(1, 9)]
    ind = independence(t)
    assert ind["shared_pct"] == 0.0
    assert "heavily clustered" not in format_validation(validate(t))


def test_independence_handles_intraday_timestamps():
    """ORB records carry full timestamps; they must collapse to dates."""
    t = [tr("A", "2024-03-01 14:35:00", 1.0), tr("B", "2024-03-01 15:05:00", 1.0)]
    assert independence(t)["distinct_entry_dates"] == 1


# ── Cost sensitivity ─────────────────────────────────────────────────────────


def test_cost_sensitivity_separates_no_edge_from_eroded_edge():
    """Gross-negative means there was never an edge to erode."""

    def run(cost):
        return [tr("A", "2024-01-01", -0.09 - cost), tr("B", "2024-01-02", -0.09 - cost)]

    rows = cost_sensitivity(run)
    assert [r["round_trip_cost_pct"] for r in rows] == [0.0, 0.30, 0.60]
    assert rows[0]["expectancy_pct"] < 0, "already negative before costs"
    assert rows[2]["expectancy_pct"] < rows[0]["expectancy_pct"]
