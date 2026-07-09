"""Backtest harness: historical Form 4 P-buys -> simulated fills + metrics.

Honesty first (also stated in the README): backtest fills are **idealized**.
There is no slippage, no partial fills, no liquidity cap, and entries/exits use
clean daily bars. This will OVERSTATE performance versus paper trading, which
itself overstates versus live. Treat the numbers as an upper bound and a sanity
check on the logic, not a forecast.

Simulation model
----------------
* Input: a CSV of historical filings with columns
  ``filed_date,ticker,owner,shares,price`` (one open-market P buy per row), or a
  list of :class:`InsiderBuy`.
* Qualify with the SAME filters as live (size / cluster).
* Enter at the next daily open after the filing.
* Exit on daily bars using the SAME trailing / hard / max-hold rules.
* Report: total return, win rate, avg hold days, max drawdown, trade count, and
  a per-trade log.

Daily bars are pulled from Alpaca's historical data if credentials are present;
otherwise you can inject a price frame for offline/deterministic testing.
"""

from __future__ import annotations

import argparse
from dataclasses import asdict, dataclass
from datetime import UTC, date, datetime

import pandas as pd

from config.settings import Settings, get_settings
from src.signals.filters import qualify_signals
from src.signals.models import InsiderBuy


@dataclass
class TradeRecord:
    ticker: str
    entry_date: str
    entry_price: float
    exit_date: str
    exit_price: float
    hold_days: int
    return_pct: float
    trigger: str


def buys_from_csv(path: str) -> list[InsiderBuy]:
    """Load historical P-buys from a CSV of filings."""
    df = pd.read_csv(path)
    buys: list[InsiderBuy] = []
    for _, r in df.iterrows():
        filed = pd.to_datetime(r["filed_date"]).to_pydatetime().replace(tzinfo=UTC)
        buys.append(
            InsiderBuy(
                accession_no=str(r.get("accession_no", f"{r['ticker']}-{r['filed_date']}")),
                issuer_cik=str(r.get("cik", "")),
                issuer_name=str(r.get("issuer", r["ticker"])),
                ticker=str(r["ticker"]).upper(),
                owner_name=str(r.get("owner", "unknown")),
                owner_is_officer=bool(r.get("is_officer", False)),
                owner_is_director=bool(r.get("is_director", False)),
                owner_is_ten_pct=bool(r.get("is_ten_pct", False)),
                transaction_date=filed.date(),
                shares=float(r["shares"]),
                price_per_share=float(r["price"]),
                filed_at=filed,
            )
        )
    return buys


def simulate_trade(
    ticker: str,
    signal_date: date,
    bars: pd.DataFrame,
    settings: Settings,
) -> TradeRecord | None:
    """Simulate one trade on daily bars.

    ``bars`` must be indexed by date with columns ``open``, ``high``, ``low``,
    ``close`` for the ticker, sorted ascending. Enters at the next open after
    ``signal_date`` and applies trailing/hard/max-hold exits day by day.
    """
    future = bars[bars.index > pd.Timestamp(signal_date)]
    if future.empty:
        return None

    entry_row = future.iloc[0]
    entry_price = float(entry_row["open"])
    entry_date = future.index[0]
    if entry_price <= 0:
        return None

    hwm = entry_price
    hard_stop = entry_price * (1 - settings.hard_stop_pct / 100.0)

    held = future.iloc[1:]  # days after entry
    for i, (ts, row) in enumerate(held.iterrows(), start=1):
        high = float(row["high"])
        low = float(row["low"])
        close = float(row["close"])
        hwm = max(hwm, high)
        trail_stop = hwm * (1 - settings.trail_pct / 100.0)

        # Conservative intraday ordering: check hard stop first, then trail.
        if low <= hard_stop:
            return _record(ticker, entry_date, entry_price, ts, hard_stop, i, "hard_stop")
        if low <= trail_stop:
            return _record(ticker, entry_date, entry_price, ts, trail_stop, i, "trailing_stop")
        if i >= settings.max_hold_days:
            return _record(ticker, entry_date, entry_price, ts, close, i, "max_hold")

    # Ran out of data — close at the last available close.
    last_ts = future.index[-1]
    last_close = float(future.iloc[-1]["close"])
    return _record(ticker, entry_date, entry_price, last_ts, last_close, len(held), "eod_data")


def _record(
    ticker, entry_date, entry_price, exit_ts, exit_price, hold_days, trigger
) -> TradeRecord:
    ret = (exit_price - entry_price) / entry_price * 100.0
    return TradeRecord(
        ticker=ticker,
        entry_date=str(pd.Timestamp(entry_date).date()),
        entry_price=round(entry_price, 4),
        exit_date=str(pd.Timestamp(exit_ts).date()),
        exit_price=round(exit_price, 4),
        hold_days=hold_days,
        return_pct=round(ret, 2),
        trigger=trigger,
    )


def summarize(trades: list[TradeRecord], starting_equity: float) -> dict:
    """Compute headline metrics from a list of trades (equal-weight compounding)."""
    if not trades:
        return {"trades": 0, "note": "no trades"}

    returns = [t.return_pct / 100.0 for t in trades]
    wins = [r for r in returns if r > 0]

    # Equal-weight sequential compounding as a simple portfolio proxy.
    equity = starting_equity
    curve = [equity]
    for r in returns:
        equity *= 1 + r
        curve.append(equity)

    peak = curve[0]
    max_dd = 0.0
    for v in curve:
        peak = max(peak, v)
        dd = (v - peak) / peak
        max_dd = min(max_dd, dd)

    return {
        "trades": len(trades),
        "total_return_pct": round((equity / starting_equity - 1) * 100, 2),
        "win_rate_pct": round(len(wins) / len(trades) * 100, 1),
        "avg_return_pct": round(sum(returns) / len(returns) * 100, 2),
        "avg_hold_days": round(sum(t.hold_days for t in trades) / len(trades), 1),
        "max_drawdown_pct": round(max_dd * 100, 2),
    }


def run_backtest(
    buys: list[InsiderBuy],
    price_frames: dict[str, pd.DataFrame],
    settings: Settings | None = None,
) -> tuple[list[TradeRecord], dict]:
    """Qualify buys, simulate each, and return (trades, metrics).

    ``price_frames`` maps ticker -> daily OHLC DataFrame. Callers supply these so
    the harness is testable offline without hitting the network.
    """
    settings = settings or get_settings()
    signals = qualify_signals(buys, settings)

    trades: list[TradeRecord] = []
    for sig in signals:
        frame = price_frames.get(sig.ticker)
        if frame is None or frame.empty:
            continue
        signal_date = min(b.transaction_date for b in sig.buys)
        rec = simulate_trade(sig.ticker, signal_date, frame, settings)
        if rec:
            trades.append(rec)

    metrics = summarize(trades, settings.starting_equity)
    return trades, metrics


def _fetch_price_frames(tickers: set[str], start: date, end: date) -> dict[str, pd.DataFrame]:
    """Pull daily bars from Alpaca for the backtest window."""
    from alpaca.data.enums import DataFeed
    from alpaca.data.historical import StockHistoricalDataClient
    from alpaca.data.requests import StockBarsRequest
    from alpaca.data.timeframe import TimeFrame

    s = get_settings()
    feed = {"iex": DataFeed.IEX, "sip": DataFeed.SIP}.get(s.alpaca_data_feed.lower(), DataFeed.IEX)
    client = StockHistoricalDataClient(api_key=s.alpaca_api_key, secret_key=s.alpaca_secret_key)
    frames: dict[str, pd.DataFrame] = {}
    for ticker in tickers:
        req = StockBarsRequest(
            symbol_or_symbols=ticker,
            timeframe=TimeFrame.Day,
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
        df.index = pd.to_datetime(df.index).tz_localize(None)
        frames[ticker] = df.sort_index()
    return frames


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Backtest insider-copy strategy on historical bars."
    )
    parser.add_argument("--csv", required=True, help="CSV of historical P-buys.")
    parser.add_argument("--start", required=True, help="Backtest start YYYY-MM-DD.")
    parser.add_argument("--end", required=True, help="Backtest end YYYY-MM-DD.")
    parser.add_argument("--out", default=None, help="Optional per-trade log CSV output path.")
    args = parser.parse_args()

    settings = get_settings()
    # Historical bars come from Alpaca; the CLI needs paper keys to fetch them.
    # (The importable run_backtest() takes injected frames and needs no keys.)
    settings.require_alpaca_keys()

    buys = buys_from_csv(args.csv)
    tickers = {b.ticker for b in buys if b.ticker}
    start = datetime.strptime(args.start, "%Y-%m-%d").date()
    end = datetime.strptime(args.end, "%Y-%m-%d").date()

    frames = _fetch_price_frames(tickers, start, end)
    trades, metrics = run_backtest(buys, frames, settings)

    print("\n=== Backtest metrics (IDEALIZED — no slippage/liquidity; overstates live) ===")
    for k, v in metrics.items():
        print(f"  {k}: {v}")
    print(f"\n  per-trade log ({len(trades)} trades):")
    for t in trades:
        print(
            f"    {t.ticker:<8} {t.entry_date}->{t.exit_date} "
            f"{t.return_pct:+.1f}% ({t.trigger}, {t.hold_days}d)"
        )

    if args.out and trades:
        pd.DataFrame([asdict(t) for t in trades]).to_csv(args.out, index=False)
        print(f"\n  wrote per-trade log to {args.out}")


if __name__ == "__main__":
    main()
