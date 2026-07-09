"""Exit manager: bot-owned trailing stop + hard stop + max-hold.

The insider tells us when they bought, not when to sell — so the bot owns exits.
Because Alpaca fractional/notional entries don't support native trailing-stop
orders, we manage the trail *in the bot*: track each position's high-water mark
and exit when drawdown from the peak exceeds ``TRAIL_PCT``.

Exit precedence for each position, checked every trading morning:
1. hard stop  — price <= entry * (1 - HARD_STOP_PCT)
2. trailing   — price <= high_water_mark * (1 - TRAIL_PCT)
3. max hold   — held for >= MAX_HOLD_DAYS trading days
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime

from config.settings import Settings
from src.broker.alpaca_client import AlpacaBroker
from src.broker.market_data import MarketData
from src.notify.notifier import get_logger, notify_fill
from src.state.repo import PositionRow, Repo

_log = get_logger("exit")


@dataclass(frozen=True)
class ExitDecision:
    should_exit: bool
    trigger: str | None
    new_high_water_mark: float


def evaluate_exit(
    position: PositionRow,
    current_price: float,
    settings: Settings,
    now: datetime | None = None,
) -> ExitDecision:
    """Pure exit logic for one position. Also returns the updated HWM.

    ``entry_at`` is an ISO timestamp; max-hold uses calendar days as a simple,
    conservative proxy for trading days (it never exits *earlier* than the
    trading-day count would).
    """
    now = now or datetime.now(UTC)
    hwm = max(position.high_water_mark, current_price)

    hard_stop_price = position.entry_price * (1 - settings.hard_stop_pct / 100.0)
    if current_price <= hard_stop_price:
        return ExitDecision(True, "hard_stop", hwm)

    trail_price = hwm * (1 - settings.trail_pct / 100.0)
    if current_price <= trail_price:
        return ExitDecision(True, "trailing_stop", hwm)

    held_days = _calendar_days_held(position.entry_at, now)
    if held_days >= settings.max_hold_days:
        return ExitDecision(True, "max_hold", hwm)

    return ExitDecision(False, None, hwm)


def run_exit_pass(
    settings: Settings,
    repo: Repo,
    broker: AlpacaBroker,
    market: MarketData,
) -> None:
    """Check every open position and exit those that trigger."""
    positions = repo.open_positions()
    if not positions:
        _log.info("no_open_positions")
        return

    for pos in positions:
        price = market.latest_price(pos.ticker)
        if price is None:
            _log.warning("exit_no_price", ticker=pos.ticker)
            continue

        decision = evaluate_exit(pos, price, settings)

        # Always persist an updated high-water mark, even when not exiting.
        if decision.new_high_water_mark > pos.high_water_mark:
            repo.update_high_water_mark(pos.ticker, decision.new_high_water_mark)

        if not decision.should_exit:
            _log.debug(
                "position_held",
                ticker=pos.ticker,
                price=price,
                hwm=decision.new_high_water_mark,
            )
            continue

        result = broker.close_position(pos.ticker, reason=decision.trigger or "exit")
        repo.log_trade(
            ticker=pos.ticker,
            side="sell",
            qty=pos.qty,
            price=price,
            notional=round(pos.qty * price, 2),
            order_id=result.order_id,
            reason=f"exit:{decision.trigger}",
        )
        if not result.dry_run:
            repo.close_position(pos.ticker)
        notify_fill(
            pos.ticker,
            "sell",
            round(pos.qty * price, 2),
            result.order_id or "",
            trigger=decision.trigger,
        )


def _calendar_days_held(entry_at_iso: str, now: datetime) -> int:
    try:
        entry_dt = datetime.fromisoformat(entry_at_iso)
    except ValueError:
        return 0
    if entry_dt.tzinfo is None:
        entry_dt = entry_dt.replace(tzinfo=UTC)
    return (now - entry_dt).days
