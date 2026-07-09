"""Notional position sizing.

Fixed equal-weight notional per name (``DOLLARS_PER_POSITION``), with a hard cap
so a single position can never exceed ``MAX_POSITION_EQUITY_PCT`` of account
equity. Notional orders mean fractional shares, so we size in dollars, not
shares.
"""

from __future__ import annotations

from dataclasses import dataclass

from config.settings import Settings


@dataclass(frozen=True)
class SizingDecision:
    """Result of a sizing calculation."""

    notional: float
    approved: bool
    reason: str | None = None


def size_position(
    settings: Settings,
    equity: float,
    available_cash: float | None = None,
) -> SizingDecision:
    """Decide the dollar notional for a new entry.

    * Base size is ``dollars_per_position``.
    * Never let a single position exceed ``max_position_equity_pct`` of equity.
    * Never size larger than available cash (when provided).
    * A size that rounds below $1 is rejected (Alpaca's notional minimum).
    """
    if equity <= 0:
        return SizingDecision(0.0, False, "non_positive_equity")

    notional = float(settings.dollars_per_position)

    equity_cap = equity * (settings.max_position_equity_pct / 100.0)
    if notional > equity_cap:
        notional = equity_cap

    if available_cash is not None:
        if available_cash < 1.0:
            return SizingDecision(0.0, False, "insufficient_cash")
        if notional > available_cash:
            notional = available_cash

    notional = round(notional, 2)
    if notional < 1.0:
        return SizingDecision(0.0, False, "below_min_notional")

    return SizingDecision(notional, True, None)
