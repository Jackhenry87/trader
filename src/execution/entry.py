"""Entry pipeline: qualify -> size -> guard -> place (or dry-run log).

Two phases, matching the schedule:

* :func:`gather_and_queue` runs after close: qualify the day's signals, apply the
  liquidity screen and dedupe, and persist survivors to the ``signals`` queue.
* :func:`place_queued_entries` runs after open: for each queued signal, size it,
  run risk guards, and place a notional buy (or log the intent in dry-run).
"""

from __future__ import annotations

import json

from config.settings import Settings
from src.broker.alpaca_client import AlpacaBroker
from src.broker.market_data import MarketData
from src.execution.sizing import size_position
from src.notify.notifier import get_logger, notify, notify_fill
from src.risk.guards import check_entry_allowed
from src.signals.filters import (
    dedupe_against_holdings,
    passes_liquidity,
    qualify_signals,
)
from src.signals.models import InsiderBuy, Signal
from src.state.repo import Repo

_log = get_logger("entry")


def gather_and_queue(
    buys: list[InsiderBuy],
    settings: Settings,
    repo: Repo,
    market: MarketData,
    held_tickers: set[str],
    open_order_tickers: set[str],
) -> list[Signal]:
    """Qualify raw buys, screen liquidity + holdings, persist queued signals.

    Returns the list of signals actually queued. Every rejection is logged with
    a reason so the dry-run/audit trail is complete.
    """
    signals = qualify_signals(buys, settings)
    _log.info("signals_qualified", count=len(signals))

    kept, rejected = dedupe_against_holdings(signals, held_tickers, open_order_tickers)
    for sig, reason in rejected:
        notify("signal_rejected", level="info", ticker=sig.ticker, reason=reason)

    queued: list[Signal] = []
    for sig in kept:
        if repo.has_queued_signal_for(sig.ticker):
            notify("signal_rejected", level="info", ticker=sig.ticker, reason="already_queued")
            continue

        snap = market.liquidity(sig.ticker)
        ok, reason = passes_liquidity(snap.price, snap.avg_dollar_volume, settings)
        if not ok:
            notify(
                "signal_rejected",
                level="info",
                ticker=sig.ticker,
                reason=reason,
                price=snap.price,
                avg_dollar_volume=snap.avg_dollar_volume,
            )
            continue

        repo.queue_signal(sig)
        queued.append(sig)
        notify(
            "signal_queued",
            level="info",
            ticker=sig.ticker,
            kind=sig.kind.value,
            total_value_usd=round(sig.total_value_usd, 2),
            insiders=sig.distinct_insiders,
        )
    return queued


def place_queued_entries(
    settings: Settings,
    repo: Repo,
    broker: AlpacaBroker,
    market: MarketData,
) -> None:
    """Place all queued entries subject to sizing + risk guards.

    Refreshes the account snapshot for each entry so the daily-loss and
    position-count guards see up-to-date state as positions are added.
    """
    queued = repo.queued_signals()
    if not queued:
        _log.info("no_queued_entries")
        return

    held = broker.get_position_symbols()
    pending = broker.open_order_symbols()

    for row in queued:
        ticker = row["ticker"].upper()
        signal_id = row["id"]

        if ticker in held or ticker in pending:
            repo.set_signal_status(signal_id, "skipped")
            notify("entry_skipped", level="info", ticker=ticker, reason="already_held_or_pending")
            continue

        snapshot = broker.snapshot()
        sizing = size_position(settings, equity=snapshot.equity, available_cash=snapshot.cash)
        if not sizing.approved:
            repo.set_signal_status(signal_id, "skipped")
            notify("entry_skipped", level="warning", ticker=ticker, reason=sizing.reason)
            continue

        guard = check_entry_allowed(settings, snapshot, sizing.notional)
        if not guard.allowed:
            repo.set_signal_status(signal_id, "skipped")
            notify("guard_tripped", level="warning", ticker=ticker, reason=guard.reason)
            continue

        result = broker.place_notional_buy(ticker, sizing.notional)
        repo.set_signal_status(signal_id, "placed" if not result.dry_run else "skipped")
        repo.log_trade(
            ticker=ticker,
            side="buy",
            qty=None,
            price=None,
            notional=sizing.notional,
            order_id=result.order_id,
            reason=f"entry:{row['kind']}",
        )

        if result.dry_run:
            notify("would_place_entry", level="info", ticker=ticker, notional=sizing.notional)
        else:
            # Record the position; entry price/HWM are reconciled once filled.
            price = market.latest_price(ticker)
            if price:
                qty = round(sizing.notional / price, 6) if price else 0.0
                repo.upsert_position(ticker, entry_price=price, qty=qty, high_water_mark=price)
            notify_fill(ticker, "buy", sizing.notional, result.order_id or "", kind=row["kind"])


def buys_from_detail(detail_json: str) -> dict:
    """Helper to decode a persisted signal's detail JSON (used by reconcilers)."""
    try:
        return json.loads(detail_json) if detail_json else {}
    except json.JSONDecodeError:
        return {}
