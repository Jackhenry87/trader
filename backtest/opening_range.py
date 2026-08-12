"""Opening Range Breakout (ORB) backtest on intraday bars.

The rule
--------
Take the high and low of the first ``range_minutes`` of the regular session —
the *opening range*. Go long when price breaks above the range high (and/or
short below the low). Stop at the opposite side of the range. Exit at the
session close. Never hold overnight.

Why this one is worth testing at all
------------------------------------
Unlike an arbitrary indicator crossover, ORB has a mechanism: information
accumulated overnight resolves at the open, and intraday volume and volatility
are reliably highest in the first hour. The opening range is also a level a
great many participants watch, so it attracts resting orders. That is a reason
for *activity*, which is a necessary condition for an edge — not a sufficient
one. The strategy is also decades old (Crabel, early 1990s) and very widely
traded, so any edge has had a long time to be competed away.

Bias controls
-------------
Breakout backtests flatter themselves in a specific way: it is tempting to fill
at the breakout level itself, which quietly assumes a resting stop order got a
perfect fill in the exact moment of fastest movement. This module refuses that
and three related shortcuts:

1. **No same-bar fill.** A breakout detected on bar *i* fills at the **open of
   bar i+1**. Filling at the range level assumes zero slippage precisely where
   slippage is worst.
2. **The entry bar's low counts against the stop.** A breakout that immediately
   fails on its entry bar must be able to stop out on that bar.
3. **Every position is closed** at the session close, tagged ``session_close``.
   Nothing is dropped, nothing is held overnight.
4. **Costs are charged both sides**, defaulting to 0.30% round trip. Opening
   spreads are the widest of the day, so if anything this is generous.

PDT
---
Every ORB trade is a same-session round trip — a day trade. Under $25k equity
the pattern-day-trader rule caps you at 3 in 5 rolling business days. The
metrics therefore include ``max_day_trades_in_5d`` and a ``pdt_warning``,
because a strategy that is profitable but untradeable at your account size is
not a strategy you can use.

Nothing here claims ORB works. It is an instrument for finding out.
"""

from __future__ import annotations

import argparse
import json
from dataclasses import dataclass, replace
from datetime import date

import pandas as pd

from backtest.run_backtest import TradeRecord, summarize

_REQUIRED_COLUMNS = ("open", "high", "low", "close")
_PDT_LIMIT = 3  # day trades allowed in 5 rolling business days under $25k


@dataclass(frozen=True)
class ORBParams:
    """Strategy and cost parameters."""

    range_minutes: int = 15
    direction: str = "long"  # long | short | both
    # Take profit at N x the initial risk (range width). None = hold to close.
    target_r: float | None = None
    commission_pct: float = 0.1
    slippage_pct: float = 0.05

    @property
    def round_trip_cost_pct(self) -> float:
        return (self.commission_pct + self.slippage_pct) * 2

    def validate(self) -> None:
        if self.range_minutes < 1:
            raise ValueError("range_minutes must be >= 1")
        if self.direction not in ("long", "short", "both"):
            raise ValueError("direction must be one of: long, short, both")
        if self.target_r is not None and self.target_r <= 0:
            raise ValueError("target_r must be > 0 when set")


def session_days(bars: pd.DataFrame) -> list[tuple[date, pd.DataFrame]]:
    """Split a DatetimeIndex-ed intraday frame into (session_date, bars) pairs."""
    if not isinstance(bars.index, pd.DatetimeIndex):
        raise ValueError("bars must have a DatetimeIndex")
    return [(d, g) for d, g in bars.groupby(bars.index.date)]


def opening_range(
    day_bars: pd.DataFrame, range_minutes: int
) -> tuple[float, float, pd.DataFrame] | None:
    """Return (range_high, range_low, bars_after_the_range) for one session.

    The range is built only from bars whose timestamp falls strictly inside the
    first ``range_minutes`` of that session's first bar. Returns None when the
    session is too short to have both a range and something to trade after it.
    """
    if day_bars.empty:
        return None
    start = day_bars.index[0]
    cutoff = start + pd.Timedelta(minutes=range_minutes)

    in_range = day_bars[day_bars.index < cutoff]
    after = day_bars[day_bars.index >= cutoff]
    if in_range.empty or len(after) < 2:
        # Need at least one bar to signal on and one to fill on.
        return None
    return float(in_range["high"].max()), float(in_range["low"].min()), after


def simulate_session(
    ticker: str,
    day_bars: pd.DataFrame,
    params: ORBParams,
) -> TradeRecord | None:
    """Run ORB over a single session. At most one trade per session."""
    rng = opening_range(day_bars, params.range_minutes)
    if rng is None:
        return None
    hi, lo, after = rng
    if hi <= lo:  # degenerate/flat range
        return None

    long_ok = params.direction in ("long", "both")
    short_ok = params.direction in ("short", "both")

    # Signal on bar i, fill on bar i+1's open.
    for i in range(len(after) - 1):
        bar = after.iloc[i]
        nxt = after.iloc[i + 1]
        nxt_ts = after.index[i + 1]

        side = None
        if long_ok and float(bar["high"]) > hi:
            side = "long"
        elif short_ok and float(bar["low"]) < lo:
            side = "short"
        if side is None:
            continue

        entry = float(nxt["open"])
        if entry <= 0:
            return None

        # Stop sits at the far side of the range; risk is the range width.
        stop = lo if side == "long" else hi
        risk = abs(entry - stop)
        target = None
        if params.target_r is not None and risk > 0:
            target = (
                entry + params.target_r * risk
                if side == "long"
                else (entry - params.target_r * risk)
            )

        remaining = after.iloc[i + 1 :]
        return _walk_position(ticker, side, entry, nxt_ts, stop, target, remaining, params)

    return None


def _walk_position(
    ticker: str,
    side: str,
    entry: float,
    entry_ts,
    stop: float,
    target: float | None,
    bars: pd.DataFrame,
    params: ORBParams,
) -> TradeRecord:
    """Walk forward from the entry bar to a stop, target, or the session close.

    The entry bar is included, so a breakout that fails immediately can stop out
    on the same bar it filled on. Stops are checked before targets — the
    pessimistic ordering when a single bar's range spans both.
    """
    for ts, row in bars.iterrows():
        low, high = float(row["low"]), float(row["high"])

        if side == "long":
            if low <= stop:
                return _record(ticker, side, entry_ts, entry, ts, stop, "stop", params)
            if target is not None and high >= target:
                return _record(ticker, side, entry_ts, entry, ts, target, "target", params)
        else:
            if high >= stop:
                return _record(ticker, side, entry_ts, entry, ts, stop, "stop", params)
            if target is not None and low <= target:
                return _record(ticker, side, entry_ts, entry, ts, target, "target", params)

    last_ts = bars.index[-1]
    return _record(
        ticker,
        side,
        entry_ts,
        entry,
        last_ts,
        float(bars.iloc[-1]["close"]),
        "session_close",
        params,
    )


def _record(
    ticker: str,
    side: str,
    entry_ts,
    entry: float,
    exit_ts,
    exit_px: float,
    trigger: str,
    params: ORBParams,
) -> TradeRecord:
    """Build a TradeRecord, net of costs, with short P/L sign-corrected."""
    gross = (exit_px - entry) / entry * 100.0
    if side == "short":
        gross = -gross
    return TradeRecord(
        ticker=ticker,
        entry_date=str(pd.Timestamp(entry_ts)),
        entry_price=round(entry, 4),
        exit_date=str(pd.Timestamp(exit_ts)),
        exit_price=round(exit_px, 4),
        hold_days=0,  # intraday by construction; see avg_hold_minutes in metrics
        return_pct=round(gross - params.round_trip_cost_pct, 3),
        trigger=f"{side}_{trigger}",
    )


def max_day_trades_in_window(trade_dates: list[date], window_days: int = 5) -> int:
    """Most day trades falling in any rolling window of business days."""
    if not trade_dates:
        return 0
    uniq = sorted(trade_dates)
    worst = 0
    for i, anchor in enumerate(uniq):
        end = anchor + pd.tseries.offsets.BDay(window_days - 1)
        n = sum(1 for d in uniq[i:] if pd.Timestamp(d) <= end)
        worst = max(worst, n)
    return worst


def run_orb(
    intraday_frames: dict[str, pd.DataFrame],
    params: ORBParams | None = None,
    starting_equity: float = 10_000.0,
) -> tuple[list[TradeRecord], dict]:
    """Run ORB across a universe of intraday frames and summarise."""
    params = params or ORBParams()
    params.validate()

    trades: list[TradeRecord] = []
    for ticker, frame in intraday_frames.items():
        if frame is None or frame.empty:
            continue
        missing = [c for c in _REQUIRED_COLUMNS if c not in frame.columns]
        if missing:
            raise ValueError(f"{ticker}: bars missing column(s): {', '.join(missing)}")
        if not frame.index.is_monotonic_increasing:
            raise ValueError(f"{ticker}: bars must be sorted ascending")
        for _day, day_bars in session_days(frame):
            rec = simulate_session(ticker, day_bars, params)
            if rec:
                trades.append(rec)

    trades.sort(key=lambda t: t.entry_date)
    metrics = summarize(trades, starting_equity)

    if trades:
        metrics["expectancy_pct"] = round(sum(t.return_pct for t in trades) / len(trades), 3)
        metrics["total_cost_drag_pct"] = round(params.round_trip_cost_pct * len(trades), 2)
        by_trigger: dict[str, int] = {}
        for t in trades:
            by_trigger[t.trigger] = by_trigger.get(t.trigger, 0) + 1
        metrics["exits_by_trigger"] = by_trigger

        mins = [
            (pd.Timestamp(t.exit_date) - pd.Timestamp(t.entry_date)).total_seconds() / 60
            for t in trades
        ]
        metrics["avg_hold_minutes"] = round(sum(mins) / len(mins), 1)

        # Every ORB trade is a same-session round trip, i.e. a day trade.
        days = [pd.Timestamp(t.entry_date).date() for t in trades]
        worst = max_day_trades_in_window(days)
        metrics["day_trades"] = len(trades)
        metrics["max_day_trades_in_5d"] = worst
        if worst > _PDT_LIMIT:
            metrics["pdt_warning"] = (
                f"peaks at {worst} day trades in 5 business days; accounts under "
                f"$25k are limited to {_PDT_LIMIT}. This strategy is not tradeable "
                "as-is at that account size."
            )

    metrics["params"] = {
        "range_minutes": params.range_minutes,
        "direction": params.direction,
        "target_r": params.target_r,
        "round_trip_cost_pct": params.round_trip_cost_pct,
    }
    return trades, metrics


def parameter_sweep(
    intraday_frames: dict[str, pd.DataFrame],
    base: ORBParams | None = None,
    range_minutes: tuple[int, ...] = (5, 15, 30, 60),
    directions: tuple[str, ...] = ("long", "both"),
) -> list[dict]:
    """Grid over range length and direction. Read it pessimistically.

    A real effect is broadly positive across neighbouring parameters. If only
    one or two cells work, that is a curve-fit — the mean-reversion module's
    random-walk sweep produced 3 profitable cells out of 9 on data with no
    structure at all.
    """
    base = base or ORBParams()
    rows: list[dict] = []
    for rm in range_minutes:
        for d in directions:
            _, m = run_orb(intraday_frames, replace(base, range_minutes=rm, direction=d))
            rows.append(
                {
                    "range_minutes": rm,
                    "direction": d,
                    "trades": m.get("trades", 0),
                    "total_return_pct": m.get("total_return_pct"),
                    "win_rate_pct": m.get("win_rate_pct"),
                    "expectancy_pct": m.get("expectancy_pct"),
                    "max_drawdown_pct": m.get("max_drawdown_pct"),
                }
            )
    return rows


def fetch_intraday_frames(
    tickers: set[str], start: date, end: date, minutes: int = 5
) -> dict[str, pd.DataFrame]:
    """Pull intraday bars from Alpaca for the backtest window.

    Regular session only (13:30–20:00 UTC), so the opening range is the real
    market open and not a pre-market print.
    """
    from datetime import UTC, datetime

    from alpaca.data.enums import DataFeed
    from alpaca.data.historical import StockHistoricalDataClient
    from alpaca.data.requests import StockBarsRequest
    from alpaca.data.timeframe import TimeFrame, TimeFrameUnit

    from config.settings import get_settings

    s = get_settings()
    feed = {"iex": DataFeed.IEX, "sip": DataFeed.SIP}.get(s.alpaca_data_feed.lower(), DataFeed.IEX)
    client = StockHistoricalDataClient(api_key=s.alpaca_api_key, secret_key=s.alpaca_secret_key)

    frames: dict[str, pd.DataFrame] = {}
    for ticker in tickers:
        req = StockBarsRequest(
            symbol_or_symbols=ticker,
            timeframe=TimeFrame(minutes, TimeFrameUnit.Minute),
            start=datetime(start.year, start.month, start.day, tzinfo=UTC),
            end=datetime(end.year, end.month, end.day, tzinfo=UTC),
            feed=feed,
        )
        try:
            bars = client.get_stock_bars(req)
            rows = bars.data.get(ticker, [])
        except Exception:  # noqa: BLE001
            rows = []
        if not rows:
            continue
        df = pd.DataFrame(
            [
                {
                    "date": b.timestamp,
                    "open": b.open,
                    "high": b.high,
                    "low": b.low,
                    "close": b.close,
                }
                for b in rows
            ]
        ).set_index("date")
        df.index = pd.to_datetime(df.index)
        df = df.between_time("13:30", "20:00")  # RTH in UTC
        df.index = df.index.tz_localize(None)
        frames[ticker] = df.sort_index()
    return frames


def main() -> None:
    p = argparse.ArgumentParser(description="Opening Range Breakout backtest.")
    p.add_argument("--tickers", required=True, help="Comma-separated, e.g. SPY,QQQ")
    p.add_argument("--start", required=True, help="YYYY-MM-DD")
    p.add_argument("--end", required=True, help="YYYY-MM-DD")
    p.add_argument("--bar-minutes", type=int, default=5, help="Intraday bar size.")
    p.add_argument("--range-minutes", type=int, default=15)
    p.add_argument("--direction", default="long", choices=["long", "short", "both"])
    p.add_argument("--target-r", type=float, default=None, help="Take profit at N x risk.")
    p.add_argument("--commission-pct", type=float, default=0.1)
    p.add_argument("--slippage-pct", type=float, default=0.05)
    p.add_argument("--sweep", action="store_true")
    p.add_argument("--out", help="Write the per-trade log to this CSV.")
    args = p.parse_args()

    tickers = {t.strip().upper() for t in args.tickers.split(",") if t.strip()}
    frames = fetch_intraday_frames(
        tickers, date.fromisoformat(args.start), date.fromisoformat(args.end), args.bar_minutes
    )
    if not frames:
        raise SystemExit(
            "No intraday data returned. Check ALPACA_API_KEY/ALPACA_SECRET_KEY and "
            "ALPACA_DATA_FEED. Note the free IEX feed has thinner intraday coverage "
            "than SIP, which may matter for opening-range bars."
        )

    params = ORBParams(
        range_minutes=args.range_minutes,
        direction=args.direction,
        target_r=args.target_r,
        commission_pct=args.commission_pct,
        slippage_pct=args.slippage_pct,
    )

    if args.sweep:
        rows = parameter_sweep(frames, params)
        print(json.dumps(rows, indent=2))
        good = sum(1 for r in rows if (r["total_return_pct"] or 0) > 0)
        print(
            f"\n{good}/{len(rows)} cells profitable. A real edge is broadly "
            "positive across neighbours; a few good cells is a curve-fit."
        )
        return

    trades, metrics = run_orb(frames, params)
    print(json.dumps(metrics, indent=2))
    if args.out and trades:
        pd.DataFrame([t.__dict__ for t in trades]).to_csv(args.out, index=False)
        print(f"\nwrote {len(trades)} trades to {args.out}")


if __name__ == "__main__":
    main()
