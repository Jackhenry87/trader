"""Z-score (Bollinger) mean-reversion backtest.

Separate from the insider-copy harness in ``run_backtest.py``: that one is
signal-driven (a Form 4 buy arrives, we simulate holding it). This one generates
its own entries from price alone, and exits when price reverts to its mean
rather than on a trailing stop.

The rule
--------
Compute a rolling z-score of the close over ``lookback`` days::

    z = (close - rolling_mean) / rolling_std

Enter long when ``z <= -entry_z`` (price stretched below its mean). Exit when
``z >= exit_z`` (reverted), or on a hard stop, or at ``max_hold_days``.

Bias controls
-------------
Mean-reversion backtests are unusually easy to flatter, because entries land on
local lows by construction. This module refuses the three shortcuts that make
that happen:

1. **No same-bar fill.** The z-score for day *i* is knowable only after day *i*
   closes, so entry fills at the *open of day i+1*. Exits work the same way.
   Filling at the signal close would buy the exact dip that triggered the
   signal — the single largest source of fake edge in this strategy family.
2. **Open positions are closed**, at the last available close, and marked
   ``eod_data``. Silently dropping them deletes exactly the trades that never
   reverted — i.e. the losers.
3. **Costs are charged**, both sides, defaulting to 0.1% commission + 0.05%
   slippage. Mean reversion trades frequently; a zero-cost run is fiction.

Stops are checked against the intraday ``low``, and a stop hit on the same bar
as an exit signal resolves as the stop — the pessimistic ordering.

Nothing here claims mean reversion works. It is an instrument for finding out.
"""

from __future__ import annotations

import argparse
import json
from dataclasses import dataclass, replace

import pandas as pd

from backtest.run_backtest import TradeRecord, summarize

_REQUIRED_COLUMNS = ("open", "high", "low", "close")


@dataclass(frozen=True)
class MeanReversionParams:
    """Strategy and cost parameters.

    ``exit_z = 0.0`` means "exit when price returns to its mean", the textbook
    formulation. Raising it holds for overshoot; lowering it exits early.
    """

    lookback: int = 20
    entry_z: float = 2.0
    exit_z: float = 0.0
    hard_stop_pct: float = 15.0
    max_hold_days: int = 20
    commission_pct: float = 0.1
    slippage_pct: float = 0.05

    @property
    def round_trip_cost_pct(self) -> float:
        """Total cost of one round trip, in percent."""
        return (self.commission_pct + self.slippage_pct) * 2

    def validate(self) -> None:
        if self.lookback < 2:
            raise ValueError("lookback must be >= 2 to have a standard deviation")
        if self.entry_z <= 0:
            raise ValueError("entry_z must be > 0 (entry is below the mean)")
        if self.max_hold_days < 1:
            raise ValueError("max_hold_days must be >= 1")


def zscore(closes: pd.Series, lookback: int) -> pd.Series:
    """Rolling z-score of ``closes``.

    Uses the sample standard deviation over a trailing window that *includes*
    the current bar — every input is known at that bar's close, so this does not
    peek. Zero-variance windows yield NaN rather than dividing by zero.
    """
    mean = closes.rolling(lookback).mean()
    std = closes.rolling(lookback).std()
    return (closes - mean).where(std > 0) / std.where(std > 0)


def simulate_mean_reversion(
    ticker: str,
    bars: pd.DataFrame,
    params: MeanReversionParams,
) -> list[TradeRecord]:
    """Run the rule over one ticker's daily bars.

    ``bars`` must be indexed by date, sorted ascending, with open/high/low/close.
    Returns net-of-cost trades; one position at a time, no pyramiding.
    """
    params.validate()
    missing = [c for c in _REQUIRED_COLUMNS if c not in bars.columns]
    if missing:
        raise ValueError(f"{ticker}: bars missing required column(s): {', '.join(missing)}")
    if not bars.index.is_monotonic_increasing:
        raise ValueError(f"{ticker}: bars must be sorted by date ascending")

    z = zscore(bars["close"], params.lookback)
    trades: list[TradeRecord] = []

    entry_price: float | None = None
    entry_ts = None
    hard_stop = 0.0
    bars_held = 0

    # Stop at len-1: every action fills on the NEXT bar's open, so the final bar
    # can only ever be a signal, never a fill.
    for i in range(len(bars) - 1):
        nxt = bars.iloc[i + 1]

        if entry_price is None:
            zi = z.iloc[i]
            if pd.notna(zi) and zi <= -params.entry_z:
                px = float(nxt["open"])
                if px <= 0:  # bad tick; skip
                    continue
                entry_price = px
                entry_ts = bars.index[i + 1]
                hard_stop = entry_price * (1 - params.hard_stop_pct / 100.0)
                bars_held = 0

                # The entry bar is a bar we are exposed on, so its low counts.
                # Without this the first stop check would land on the FOLLOWING
                # bar, letting a position that craters on its entry day escape
                # the stop for a full session — a purely optimistic omission.
                if float(nxt["low"]) <= hard_stop:
                    trades.append(
                        _record(
                            ticker,
                            entry_ts,
                            entry_price,
                            entry_ts,
                            hard_stop,
                            0,
                            "hard_stop",
                            params,
                        )
                    )
                    entry_price = None
            continue

        # In a position. The next bar is a day held.
        bars_held += 1

        # Pessimistic ordering: a stop touched intraday resolves before any
        # mean-reversion exit that the same bar's close would have triggered.
        if float(nxt["low"]) <= hard_stop:
            trades.append(
                _record(
                    ticker,
                    entry_ts,
                    entry_price,
                    bars.index[i + 1],
                    hard_stop,
                    bars_held,
                    "hard_stop",
                    params,
                )
            )
            entry_price = None
            continue

        zi = z.iloc[i]
        reverted = pd.notna(zi) and zi >= params.exit_z
        timed_out = bars_held >= params.max_hold_days
        if reverted or timed_out:
            trades.append(
                _record(
                    ticker,
                    entry_ts,
                    entry_price,
                    bars.index[i + 1],
                    float(nxt["open"]),
                    bars_held,
                    "mean_revert" if reverted else "max_hold",
                    params,
                )
            )
            entry_price = None

    # Still holding at the end of the data: close it and say so. Dropping this
    # would delete a position that never reverted, which is a loser by definition.
    if entry_price is not None:
        trades.append(
            _record(
                ticker,
                entry_ts,
                entry_price,
                bars.index[-1],
                float(bars.iloc[-1]["close"]),
                bars_held,
                "eod_data",
                params,
            )
        )

    return trades


def _record(
    ticker: str,
    entry_ts,
    entry_price: float,
    exit_ts,
    exit_price: float,
    hold_days: int,
    trigger: str,
    params: MeanReversionParams,
) -> TradeRecord:
    """Build a TradeRecord with costs already deducted from the return."""
    gross = (exit_price - entry_price) / entry_price * 100.0
    net = gross - params.round_trip_cost_pct
    return TradeRecord(
        ticker=ticker,
        entry_date=str(pd.Timestamp(entry_ts).date()),
        entry_price=round(entry_price, 4),
        exit_date=str(pd.Timestamp(exit_ts).date()),
        exit_price=round(exit_price, 4),
        hold_days=hold_days,
        return_pct=round(net, 2),
        trigger=trigger,
    )


def buy_and_hold_return_pct(bars: pd.DataFrame) -> float:
    """Benchmark: first open to last close, in percent."""
    if len(bars) < 2:
        return 0.0
    first = float(bars.iloc[0]["open"])
    if first <= 0:
        return 0.0
    return round((float(bars.iloc[-1]["close"]) - first) / first * 100.0, 2)


def run_mean_reversion(
    price_frames: dict[str, pd.DataFrame],
    params: MeanReversionParams | None = None,
    starting_equity: float = 10_000.0,
) -> tuple[list[TradeRecord], dict]:
    """Run the strategy across a universe and summarise.

    ``price_frames`` maps ticker -> daily OHLC DataFrame, supplied by the caller
    so this is testable offline. Trades are ordered by entry date so the
    sequential compounding in ``summarize`` reflects real chronology rather than
    dict iteration order.
    """
    params = params or MeanReversionParams()
    trades: list[TradeRecord] = []
    bh: dict[str, float] = {}

    for ticker, frame in price_frames.items():
        if frame is None or frame.empty:
            continue
        trades.extend(simulate_mean_reversion(ticker, frame, params))
        bh[ticker] = buy_and_hold_return_pct(frame)

    trades.sort(key=lambda t: t.entry_date)
    metrics = summarize(trades, starting_equity)

    if trades:
        metrics["expectancy_pct"] = round(sum(t.return_pct for t in trades) / len(trades), 3)
        metrics["total_cost_drag_pct"] = round(params.round_trip_cost_pct * len(trades), 2)
        by_trigger: dict[str, int] = {}
        for t in trades:
            by_trigger[t.trigger] = by_trigger.get(t.trigger, 0) + 1
        metrics["exits_by_trigger"] = by_trigger
    if bh:
        metrics["buy_and_hold_avg_pct"] = round(sum(bh.values()) / len(bh), 2)
    metrics["params"] = {
        "lookback": params.lookback,
        "entry_z": params.entry_z,
        "exit_z": params.exit_z,
        "hard_stop_pct": params.hard_stop_pct,
        "max_hold_days": params.max_hold_days,
        "round_trip_cost_pct": params.round_trip_cost_pct,
    }
    return trades, metrics


def parameter_sweep(
    price_frames: dict[str, pd.DataFrame],
    base: MeanReversionParams | None = None,
    lookbacks: tuple[int, ...] = (10, 20, 50),
    entry_zs: tuple[float, ...] = (1.5, 2.0, 2.5),
) -> list[dict]:
    """Run a grid and report each cell.

    This exists to be read pessimistically. If only a couple of cells are
    profitable, that is a curve-fit, not an edge — a real effect should be
    broadly positive across neighbouring parameters. Picking the best cell and
    reporting it as *the* result is how backtests lie.
    """
    base = base or MeanReversionParams()
    rows: list[dict] = []
    for lb in lookbacks:
        for ez in entry_zs:
            params = replace(base, lookback=lb, entry_z=ez)
            _, m = run_mean_reversion(price_frames, params)
            rows.append(
                {
                    "lookback": lb,
                    "entry_z": ez,
                    "trades": m.get("trades", 0),
                    "total_return_pct": m.get("total_return_pct"),
                    "win_rate_pct": m.get("win_rate_pct"),
                    "expectancy_pct": m.get("expectancy_pct"),
                    "max_drawdown_pct": m.get("max_drawdown_pct"),
                }
            )
    return rows


def main() -> None:
    parser = argparse.ArgumentParser(description="Z-score mean-reversion backtest.")
    parser.add_argument("--tickers", required=True, help="Comma-separated, e.g. SPY,QQQ,AAPL")
    parser.add_argument("--start", required=True, help="YYYY-MM-DD")
    parser.add_argument("--end", required=True, help="YYYY-MM-DD")
    parser.add_argument("--lookback", type=int, default=20)
    parser.add_argument("--entry-z", type=float, default=2.0)
    parser.add_argument("--exit-z", type=float, default=0.0)
    parser.add_argument("--hard-stop-pct", type=float, default=15.0)
    parser.add_argument("--max-hold-days", type=int, default=20)
    parser.add_argument("--commission-pct", type=float, default=0.1)
    parser.add_argument("--slippage-pct", type=float, default=0.05)
    parser.add_argument("--sweep", action="store_true", help="Run a parameter grid instead.")
    parser.add_argument("--out", help="Write the per-trade log to this CSV.")
    args = parser.parse_args()

    from datetime import date as _date

    from backtest.run_backtest import _fetch_price_frames

    tickers = {t.strip().upper() for t in args.tickers.split(",") if t.strip()}
    start = _date.fromisoformat(args.start)
    end = _date.fromisoformat(args.end)

    frames = _fetch_price_frames(tickers, start, end)
    if not frames:
        raise SystemExit(
            "No price data returned. Check ALPACA_API_KEY/ALPACA_SECRET_KEY and "
            "ALPACA_DATA_FEED (sip needs a paid subscription; iex is the free default)."
        )
    missing = sorted(tickers - set(frames))
    if missing:
        print(f"warning: no bars for {', '.join(missing)} — excluded from the run\n")

    params = MeanReversionParams(
        lookback=args.lookback,
        entry_z=args.entry_z,
        exit_z=args.exit_z,
        hard_stop_pct=args.hard_stop_pct,
        max_hold_days=args.max_hold_days,
        commission_pct=args.commission_pct,
        slippage_pct=args.slippage_pct,
    )

    if args.sweep:
        rows = parameter_sweep(frames, params)
        print(json.dumps(rows, indent=2))
        profitable = sum(1 for r in rows if (r["total_return_pct"] or 0) > 0)
        print(
            f"\n{profitable}/{len(rows)} parameter cells profitable. "
            "A real edge is broadly positive; a few good cells is a curve-fit."
        )
        return

    trades, metrics = run_mean_reversion(frames, params)
    print(json.dumps(metrics, indent=2))

    if args.out and trades:
        pd.DataFrame([t.__dict__ for t in trades]).to_csv(args.out, index=False)
        print(f"\nwrote {len(trades)} trades to {args.out}")


if __name__ == "__main__":
    main()
