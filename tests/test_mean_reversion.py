"""Mean-reversion backtest: mechanics, and behaviour on known ground truth.

Two groups here.

*Mechanics* pin the anti-bias properties — next-open fills, open positions
closed, costs charged, pessimistic stop ordering. These are the properties that,
if broken, manufacture edge out of nothing.

*Ground truth* runs the strategy on synthetic series whose true nature is known
by construction: a mean-reverting process (should profit), a random walk (should
not, after costs), and a downtrend (should lose). This validates that the
implementation detects mean reversion when it is really there and does not
hallucinate it when it is not. It says nothing about real markets.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from backtest.mean_reversion import (
    MeanReversionParams,
    buy_and_hold_return_pct,
    parameter_sweep,
    run_mean_reversion,
    simulate_mean_reversion,
    zscore,
)


def make_bars(closes: list[float] | np.ndarray, start: str = "2024-01-01") -> pd.DataFrame:
    """Build OHLC from a close series.

    ``open[i] = close[i-1]`` (gap-free), with a tight intraday range so stops do
    not fire incidentally. Open deliberately differs from close so that
    "filled at the next open" is distinguishable from "filled at the signal
    close" — the same-bar-fill bias would be invisible otherwise.
    """
    closes = [float(c) for c in closes]
    opens = [closes[0]] + closes[:-1]
    idx = pd.bdate_range(start=start, periods=len(closes))
    return pd.DataFrame(
        {
            "open": opens,
            "high": [max(o, c) * 1.005 for o, c in zip(opens, closes, strict=True)],
            "low": [min(o, c) * 0.995 for o, c in zip(opens, closes, strict=True)],
            "close": closes,
        },
        index=idx,
    )


def ou_series(n: int, seed: int, mu: float = 100.0, theta: float = 0.25, sigma: float = 3.0):
    """Ornstein-Uhlenbeck: genuinely mean-reverting by construction."""
    rng = np.random.default_rng(seed)
    x = np.empty(n)
    x[0] = mu
    for i in range(1, n):
        x[i] = x[i - 1] + theta * (mu - x[i - 1]) + rng.normal(0, sigma)
    return x


def random_walk(n: int, seed: int, start: float = 100.0, sigma: float = 1.5):
    """Driftless random walk: no exploitable structure."""
    rng = np.random.default_rng(seed)
    return start + np.cumsum(rng.normal(0, sigma, n))


# ── Mechanics ────────────────────────────────────────────────────────────────


def test_zscore_has_no_lookahead():
    """z at bar i must depend only on bars <= i."""
    closes = list(np.linspace(100, 120, 40))
    full = zscore(make_bars(closes)["close"], 20)
    truncated = zscore(make_bars(closes[:30])["close"], 20)
    # The first 30 values must be identical whether or not later data exists.
    pd.testing.assert_series_equal(
        full.iloc[:30].reset_index(drop=True),
        truncated.reset_index(drop=True),
        check_names=False,
    )


def test_warmup_produces_no_signal():
    """No trade can fire before the lookback window is full."""
    bars = make_bars([100.0] * 10 + [80.0])
    trades = simulate_mean_reversion("X", bars, MeanReversionParams(lookback=20))
    assert trades == []


def test_entry_fills_at_next_open_not_signal_close():
    """The core anti-bias property: no same-bar fill."""
    closes = [100.0] * 25 + [70.0, 105.0, 106.0]
    bars = make_bars(closes)
    params = MeanReversionParams(lookback=20, entry_z=1.5, hard_stop_pct=99.0)
    trades = simulate_mean_reversion("X", bars, params)

    assert trades, "expected the 70.0 dip to trigger an entry"
    t = trades[0]
    # open[i+1] == close[i] here by construction, so price alone cannot prove
    # which bar filled. The DATE can: the fill must land on the following bar.
    signal_bar = bars.index[25]
    assert t.entry_price == pytest.approx(70.0)
    assert pd.Timestamp(t.entry_date) > signal_bar, (
        "entry must be dated after the bar whose close generated the signal; "
        "filling on the signal bar is the same-bar-fill bias"
    )
    assert bars.iloc[25]["close"] == 70.0, "sanity: bar 25 is the signal bar"


def test_open_position_is_closed_at_end_of_data():
    """A position that never reverts must still be recorded as a loss."""
    # Dip triggers entry, then price keeps falling and never returns to the mean.
    closes = [100.0] * 25 + [80.0] + list(np.linspace(79.0, 40.0, 30))
    bars = make_bars(closes)
    params = MeanReversionParams(lookback=20, entry_z=1.5, hard_stop_pct=99.0, max_hold_days=999)
    trades = simulate_mean_reversion("X", bars, params)

    assert len(trades) == 1
    assert trades[0].trigger == "eod_data"
    assert trades[0].return_pct < 0, "an unreverted position is a loss and must be reported"


def test_costs_are_deducted_both_sides():
    closes = [100.0] * 25 + [70.0, 105.0, 106.0]
    bars = make_bars(closes)
    free = MeanReversionParams(
        lookback=20, entry_z=1.5, hard_stop_pct=99.0, commission_pct=0.0, slippage_pct=0.0
    )
    costed = MeanReversionParams(
        lookback=20, entry_z=1.5, hard_stop_pct=99.0, commission_pct=0.1, slippage_pct=0.05
    )
    gross = simulate_mean_reversion("X", bars, free)[0].return_pct
    net = simulate_mean_reversion("X", bars, costed)[0].return_pct
    assert costed.round_trip_cost_pct == pytest.approx(0.30)
    assert net == pytest.approx(gross - 0.30, abs=0.01)


def test_hard_stop_wins_ties_against_exit_signal():
    """Pessimistic ordering: if both could fire on a bar, the stop does."""
    closes = [100.0] * 25 + [80.0, 50.0]
    bars = make_bars(closes)
    params = MeanReversionParams(lookback=20, entry_z=1.5, hard_stop_pct=10.0)
    trades = simulate_mean_reversion("X", bars, params)
    assert trades and trades[0].trigger == "hard_stop"


def test_max_hold_forces_exit():
    closes = [100.0] * 25 + [80.0] + [80.5] * 30
    bars = make_bars(closes)
    params = MeanReversionParams(
        lookback=20, entry_z=1.5, hard_stop_pct=99.0, exit_z=5.0, max_hold_days=5
    )
    trades = simulate_mean_reversion("X", bars, params)
    assert trades and trades[0].trigger == "max_hold"
    assert trades[0].hold_days == 5


def test_rejects_malformed_input():
    with pytest.raises(ValueError, match="missing required column"):
        simulate_mean_reversion("X", pd.DataFrame({"close": [1, 2]}), MeanReversionParams())
    with pytest.raises(ValueError, match="sorted by date ascending"):
        bars = make_bars([100.0] * 30).iloc[::-1]
        simulate_mean_reversion("X", bars, MeanReversionParams())
    with pytest.raises(ValueError, match="lookback"):
        simulate_mean_reversion("X", make_bars([100.0] * 30), MeanReversionParams(lookback=1))


def test_flat_series_never_divides_by_zero():
    """Zero variance must yield NaN, not inf, and produce no trades."""
    bars = make_bars([100.0] * 60)
    z = zscore(bars["close"], 20)
    assert not np.isinf(z.to_numpy(dtype=float)).any()
    assert simulate_mean_reversion("X", bars, MeanReversionParams()) == []


# ── Ground truth ─────────────────────────────────────────────────────────────


def test_detects_edge_in_genuinely_mean_reverting_series():
    """On an OU process the strategy should make money. If not, it is broken."""
    frames = {f"OU{i}": make_bars(ou_series(600, seed=i)) for i in range(6)}
    params = MeanReversionParams(lookback=20, entry_z=1.5, exit_z=0.0, hard_stop_pct=25.0)
    trades, metrics = run_mean_reversion(frames, params)

    assert metrics["trades"] > 50, "OU series should generate a workable sample"
    assert (
        metrics["expectancy_pct"] > 0
    ), f"positive expectancy expected on a mean-reverting process, got {metrics}"
    assert metrics["win_rate_pct"] > 50


def test_no_edge_on_driftless_random_walk():
    """The honest negative control: no structure, so no edge after costs."""
    frames = {f"RW{i}": make_bars(random_walk(600, seed=100 + i)) for i in range(6)}
    params = MeanReversionParams(lookback=20, entry_z=1.5, exit_z=0.0, hard_stop_pct=25.0)
    _, metrics = run_mean_reversion(frames, params)

    assert metrics["trades"] > 20
    # A random walk has no mean to revert to; costs make it strictly negative in
    # expectation. Allow a small positive band for sampling noise, but it must
    # not look like a real edge.
    assert (
        metrics["expectancy_pct"] < 0.5
    ), f"strategy claims an edge on a random walk — that is a bug, got {metrics}"


def test_loses_on_persistent_downtrend():
    """Mean reversion buys dips; in a downtrend every dip keeps dipping."""
    frames = {"DOWN": make_bars(list(np.linspace(200.0, 50.0, 400)))}
    params = MeanReversionParams(lookback=20, entry_z=1.5, hard_stop_pct=10.0)
    trades, metrics = run_mean_reversion(frames, params)
    if trades:
        assert metrics["expectancy_pct"] < 0


def test_metrics_report_costs_benchmark_and_triggers():
    frames = {f"OU{i}": make_bars(ou_series(400, seed=200 + i)) for i in range(3)}
    trades, metrics = run_mean_reversion(frames, MeanReversionParams(entry_z=1.5))

    assert "buy_and_hold_avg_pct" in metrics
    assert "total_cost_drag_pct" in metrics
    assert "exits_by_trigger" in metrics
    assert sum(metrics["exits_by_trigger"].values()) == metrics["trades"]
    assert metrics["params"]["round_trip_cost_pct"] == pytest.approx(0.30)
    # Trades must be chronological, since summarize() compounds them in order.
    assert [t.entry_date for t in trades] == sorted(t.entry_date for t in trades)


def test_parameter_sweep_covers_the_grid():
    frames = {"OU": make_bars(ou_series(500, seed=7))}
    rows = parameter_sweep(frames, lookbacks=(10, 20), entry_zs=(1.5, 2.0))
    assert len(rows) == 4
    assert {(r["lookback"], r["entry_z"]) for r in rows} == {
        (10, 1.5),
        (10, 2.0),
        (20, 1.5),
        (20, 2.0),
    }


def test_buy_and_hold_benchmark():
    bars = make_bars([100.0, 110.0, 121.0])
    # first open (100) -> last close (121)
    assert buy_and_hold_return_pct(bars) == pytest.approx(21.0)
    assert buy_and_hold_return_pct(make_bars([100.0])) == 0.0
