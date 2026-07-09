"""Risk rails enforced before any entry is placed (spec section 5e).

These guards are the difference between a bounded paper experiment and an
unbounded one. They are pure functions over an account snapshot plus config so
they are trivially unit-testable and can't be bypassed by the execution path.
"""

from __future__ import annotations

from dataclasses import dataclass

from config.settings import Settings


@dataclass(frozen=True)
class AccountSnapshot:
    """The minimal account state the guards need to make a decision."""

    equity: float
    last_equity: float  # Equity at the previous close (for daily P/L).
    cash: float
    open_positions: int
    is_paper: bool


@dataclass(frozen=True)
class GuardResult:
    allowed: bool
    reason: str | None = None


def assert_paper(is_paper: bool, live_enabled: bool) -> None:
    """Refuse to proceed unless we're on paper (or live is explicitly enabled).

    Called on every run. This is the paper assertion required by the spec: the
    client must be paper, and if it somehow isn't, we only continue when both
    live gates are open.
    """
    if not is_paper and not live_enabled:
        raise RuntimeError(
            "SAFETY: Alpaca client is not paper and live trading is not enabled. "
            "Refusing to run. Check ALPACA_BASE_URL / ALLOW_LIVE / CONFIRM_LIVE."
        )


def daily_loss_pct(snapshot: AccountSnapshot) -> float:
    """Today's P/L as a percent of the prior close's equity (negative = loss)."""
    if snapshot.last_equity <= 0:
        return 0.0
    return (snapshot.equity - snapshot.last_equity) / snapshot.last_equity * 100.0


def check_entry_allowed(
    settings: Settings,
    snapshot: AccountSnapshot,
    prospective_notional: float,
) -> GuardResult:
    """Run every entry guard. Returns the first failure, else allowed.

    Guards, in order:
    1. Paper assertion (hard-fails elsewhere; re-checked here defensively).
    2. Daily-loss kill switch: halt NEW entries once today's P/L <= -MAX.
    3. Max concurrent positions cap.
    4. Single-position equity cap (~20% of equity).
    5. Sufficient cash for the order.
    """
    # 1. Paper gate — never place entries against a live account by accident.
    if not snapshot.is_paper and not settings.live_enabled:
        return GuardResult(False, "not_paper")

    # 2. Daily loss kill switch.
    pl = daily_loss_pct(snapshot)
    if pl <= -abs(settings.max_daily_loss_pct):
        return GuardResult(False, f"daily_loss_halt({pl:.1f}%)")

    # 3. Max open positions.
    if snapshot.open_positions >= settings.max_open_positions:
        return GuardResult(
            False, f"max_positions({snapshot.open_positions}>={settings.max_open_positions})"
        )

    # 4. Single-position equity cap.
    equity_cap = snapshot.equity * (settings.max_position_equity_pct / 100.0)
    if prospective_notional > equity_cap + 1e-9:
        return GuardResult(
            False, f"position_over_equity_cap({prospective_notional:.2f}>{equity_cap:.2f})"
        )

    # 5. Cash check.
    if prospective_notional > snapshot.cash + 1e-9:
        return GuardResult(
            False, f"insufficient_cash({prospective_notional:.2f}>{snapshot.cash:.2f})"
        )

    return GuardResult(True, None)
