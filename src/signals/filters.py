"""Signal qualification: turn raw insider buys into qualified entry signals.

A buy qualifies as an entry signal when ALL hold (spec section 5a):

* transaction code ``P`` (already enforced by the parser);
* EITHER a single filer's buy value >= ``MIN_INSIDER_BUY_USD`` (SIZE)
  OR >= ``CLUSTER_MIN_INSIDERS`` distinct insiders bought the same issuer within
  ``CLUSTER_WINDOW_DAYS`` (CLUSTER);
* passes the liquidity screen (price + average dollar volume);
* we do not already hold it and have no open entry order for it.

Liquidity is checked separately (it needs market data), so this module exposes
the pure qualification logic and a small liquidity predicate; the orchestrator
wires in the market-data lookups.
"""

from __future__ import annotations

from collections import defaultdict
from datetime import UTC, datetime

from config.settings import Settings
from src.signals.models import InsiderBuy, Signal, SignalKind


def _issuer_key(buy: InsiderBuy) -> str:
    """Group buys by ticker when available, else by issuer CIK."""
    return buy.ticker.upper() if buy.ticker else f"CIK:{buy.issuer_cik}"


def qualify_signals(
    buys: list[InsiderBuy],
    settings: Settings,
    now: datetime | None = None,
) -> list[Signal]:
    """Aggregate raw buys into qualified SIZE/CLUSTER signals per issuer.

    Cluster detection groups buys of the same issuer whose transaction dates fall
    within ``cluster_window_days`` of each other (using the span of observed
    transaction dates as a simple, conservative window check). Only issuers with
    a resolvable ticker produce signals — we can't trade a CIK.
    """
    now = now or datetime.now(UTC)
    grouped: dict[str, list[InsiderBuy]] = defaultdict(list)
    for buy in buys:
        grouped[_issuer_key(buy)].append(buy)

    signals: list[Signal] = []
    for issuer_buys in grouped.values():
        ticker = issuer_buys[0].ticker
        if not ticker:
            # No ticker resolved from the filing; can't route an order. Skip.
            continue

        # SIZE: any single buy clears the dollar threshold.
        largest = max(issuer_buys, key=lambda b: b.value_usd)
        size_qualifies = largest.value_usd >= settings.min_insider_buy_usd

        # CLUSTER: enough distinct insiders within the window.
        distinct_owners = {b.owner_name.strip().lower() for b in issuer_buys}
        in_window = _within_cluster_window(issuer_buys, settings.cluster_window_days)
        cluster_qualifies = len(distinct_owners) >= settings.cluster_min_insiders and in_window

        if not (size_qualifies or cluster_qualifies):
            continue

        # Prefer labelling as CLUSTER when both apply — cluster buying is the
        # stronger documented tilt.
        kind = SignalKind.CLUSTER if cluster_qualifies else SignalKind.SIZE

        signals.append(
            Signal(
                ticker=ticker.upper(),
                issuer_cik=issuer_buys[0].issuer_cik,
                issuer_name=issuer_buys[0].issuer_name,
                kind=kind,
                qualified_at=now,
                buys=list(issuer_buys),
            )
        )
    return signals


def _within_cluster_window(buys: list[InsiderBuy], window_days: int) -> bool:
    """True when all transaction dates span no more than ``window_days``.

    A conservative approximation of "within N trading days": we use calendar-day
    span of the observed transaction dates. Since window is small (default 5) and
    filings cluster tightly in real cluster-buying, this is adequate and never
    over-counts a cluster.
    """
    if len(buys) <= 1:
        return True
    dates = sorted(b.transaction_date for b in buys)
    span = (dates[-1] - dates[0]).days
    return span <= window_days


def passes_liquidity(
    price: float | None,
    avg_dollar_volume: float | None,
    settings: Settings,
    data_error: str | None = None,
) -> tuple[bool, str | None]:
    """Liquidity screen. Returns (ok, reject_reason).

    ``data_error`` is set when the market-data lookup itself failed. That is not
    a liquidity verdict — we never assessed the name — so it gets its own reason
    string. Callers should treat it as a system fault (see
    ``LiquiditySnapshot.data_unavailable``), not a routine rejection.
    """
    if data_error is not None:
        return False, f"data_unavailable({data_error})"
    if price is None:
        return False, "no_price"
    if price < settings.min_price:
        return False, f"price_below_min({price:.2f}<{settings.min_price})"
    if avg_dollar_volume is None:
        return False, "no_volume"
    if avg_dollar_volume < settings.min_avg_dollar_volume:
        return False, f"illiquid({avg_dollar_volume:.0f}<{settings.min_avg_dollar_volume:.0f})"
    return True, None


def dedupe_against_holdings(
    signals: list[Signal],
    held_tickers: set[str],
    open_order_tickers: set[str],
) -> tuple[list[Signal], list[tuple[Signal, str]]]:
    """Drop signals for names we already hold or have a pending entry for.

    Returns (kept, rejected) where each rejected item carries a reason string.
    """
    held = {t.upper() for t in held_tickers}
    pending = {t.upper() for t in open_order_tickers}
    kept: list[Signal] = []
    rejected: list[tuple[Signal, str]] = []
    seen: set[str] = set()

    for sig in signals:
        tkr = sig.ticker.upper()
        if tkr in held:
            rejected.append((sig, "already_held"))
        elif tkr in pending:
            rejected.append((sig, "open_entry_order"))
        elif tkr in seen:
            rejected.append((sig, "duplicate_signal"))
        else:
            seen.add(tkr)
            kept.append(sig)
    return kept, rejected
