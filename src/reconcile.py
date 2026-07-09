"""Reconcile persisted state against the broker's actual account on boot.

State can drift from reality: an order filled while the bot was down, a position
was closed manually, a restart lost an in-flight write. On boot we compare the
DB's open positions against Alpaca's real positions and log every discrepancy so
the operator (and the logs) know the true state before any new orders fly.
"""

from __future__ import annotations

from src.broker.alpaca_client import AlpacaBroker
from src.notify.notifier import get_logger, notify
from src.state.repo import Repo

_log = get_logger("reconcile")


def reconcile(repo: Repo, broker: AlpacaBroker) -> None:
    """Log drift between DB positions and broker positions; sync the DB to truth.

    The broker is the source of truth for what we actually hold. We:
    * mark DB positions closed if the broker no longer holds them;
    * adopt broker positions the DB doesn't know about (so exits still manage
      them), seeding entry price and HWM from the broker's average entry.
    """
    broker_positions = {p.symbol.upper(): p for p in broker.get_positions()}
    db_positions = {p.ticker.upper(): p for p in repo.open_positions()}

    # Positions the DB thinks are open but the broker doesn't hold -> closed.
    for ticker in set(db_positions) - set(broker_positions):
        notify("reconcile_drift", level="warning", ticker=ticker, drift="db_open_broker_absent")
        repo.close_position(ticker)

    # Positions the broker holds that the DB doesn't know about -> adopt.
    for ticker in set(broker_positions) - set(db_positions):
        pos = broker_positions[ticker]
        entry = float(getattr(pos, "avg_entry_price", 0) or 0)
        qty = abs(float(getattr(pos, "qty", 0) or 0))
        current = float(getattr(pos, "current_price", entry) or entry)
        notify("reconcile_drift", level="warning", ticker=ticker, drift="broker_open_db_absent")
        repo.upsert_position(
            ticker,
            entry_price=entry or current,
            qty=qty,
            high_water_mark=max(entry or current, current),
        )

    matched = set(db_positions) & set(broker_positions)
    _log.info(
        "reconcile_complete",
        matched=len(matched),
        adopted=len(set(broker_positions) - set(db_positions)),
        closed=len(set(db_positions) - set(broker_positions)),
    )
