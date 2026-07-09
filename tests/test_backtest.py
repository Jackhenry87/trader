"""Backtest harness tests using synthetic daily bars (no network)."""

from __future__ import annotations

from datetime import date

import pandas as pd

from backtest.run_backtest import run_backtest, simulate_trade, summarize
from tests.conftest import make_buy


def _frame(prices: list[tuple[str, float, float, float, float]]) -> pd.DataFrame:
    """Build an OHLC frame from (date, open, high, low, close) tuples."""
    df = pd.DataFrame(prices, columns=["date", "open", "high", "low", "close"])
    df["date"] = pd.to_datetime(df["date"])
    return df.set_index("date").sort_index()


def test_trailing_stop_exit_in_backtest(settings):
    # Enter at day2 open (100). Rises to 120 then falls; trail 10% -> exit ~108.
    frame = _frame(
        [
            ("2024-05-10", 99, 99, 99, 99),  # signal day
            ("2024-05-13", 100, 101, 99, 100),  # entry at open 100
            ("2024-05-14", 101, 120, 100, 118),  # HWM -> 120, trail stop 108
            ("2024-05-15", 118, 119, 105, 106),  # low 105 <= 108 -> exit
        ]
    )
    rec = simulate_trade("TST", date(2024, 5, 10), frame, settings)
    assert rec is not None
    assert rec.trigger == "trailing_stop"
    assert rec.entry_price == 100.0


def test_hard_stop_exit_in_backtest(settings):
    frame = _frame(
        [
            ("2024-05-10", 99, 99, 99, 99),
            ("2024-05-13", 100, 101, 99, 100),  # entry 100
            ("2024-05-14", 100, 100, 80, 82),  # low 80 <= hard stop 85
        ]
    )
    rec = simulate_trade("TST", date(2024, 5, 10), frame, settings)
    assert rec.trigger == "hard_stop"


def test_run_backtest_end_to_end(settings):
    buys = [make_buy("WIN", "Alice", shares=2000, price=30.0)]  # size-qualifies
    frame = _frame(
        [
            ("2024-05-10", 30, 30, 30, 30),
            ("2024-05-13", 30, 31, 30, 31),  # entry 30
            ("2024-05-14", 31, 40, 31, 39),  # HWM 40, trail 36
            ("2024-05-15", 39, 39, 34, 35),  # low 34 <= 36 -> trailing exit
        ]
    )
    trades, metrics = run_backtest(buys, {"WIN": frame}, settings)
    assert metrics["trades"] == 1
    assert trades[0].ticker == "WIN"
    assert trades[0].return_pct > 0  # exited at 36 from entry 30


def test_summarize_empty():
    assert summarize([], 200.0)["trades"] == 0
