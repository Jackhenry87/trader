"""Performance scorecard from persisted state.

The bot records every order leg in ``trades`` and every qualification decision
in ``signals``, but nothing turned that into a readable answer to "how is this
doing". This module does.

Two things it deliberately separates:

* **Realized** P/L, from closed round trips. This is the only number that is
  actually settled.
* **Unrealized** P/L on open positions, which needs a live quote and is
  therefore marked ``unavailable`` rather than guessed when market data cannot
  be reached. A report that silently prints stale or absent marks as if they
  were current is the same class of failure as a liquidity screen that treats a
  data outage as an illiquid name.

The signal funnel is included because "how is this doing" is not only about
trades taken. A run that queued nothing is very different from a run that
queued ten names and lost on all of them, and the rejection reasons say which.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import datetime


@dataclass(frozen=True)
class RoundTrip:
    """One completed buy -> sell cycle."""

    ticker: str
    entry_at: str
    exit_at: str
    qty: float
    entry_price: float
    exit_price: float
    pnl: float
    return_pct: float
    exit_reason: str

    @property
    def hold_days(self) -> int | None:
        try:
            a = datetime.fromisoformat(self.entry_at)
            b = datetime.fromisoformat(self.exit_at)
        except (ValueError, TypeError):
            return None
        return max(0, (b - a).days)


def round_trips(rows: list[sqlite3.Row]) -> list[RoundTrip]:
    """Pair buy legs with sell legs, per ticker, in chronological order.

    The bot takes one position per ticker at a time, so pairing is a simple
    FIFO: buys open a lot, a sell closes whatever is open. Legs missing a price
    or quantity (a dry-run entry, or an order that never filled) cannot produce
    a P/L figure and are skipped rather than counted as zero.
    """
    by_ticker: dict[str, list[sqlite3.Row]] = {}
    for r in rows:
        by_ticker.setdefault(r["ticker"], []).append(r)

    out: list[RoundTrip] = []
    for ticker, legs in by_ticker.items():
        open_qty = 0.0
        open_cost = 0.0
        opened_at: str | None = None

        for leg in sorted(legs, key=lambda x: x["id"]):
            price, qty = leg["price"], leg["qty"]
            if price is None or qty is None or qty <= 0:
                continue

            if leg["side"] == "buy":
                if open_qty == 0.0:
                    opened_at = leg["placed_at"]
                open_qty += float(qty)
                open_cost += float(qty) * float(price)
            elif leg["side"] == "sell" and open_qty > 0:
                closed = min(float(qty), open_qty)
                avg_entry = open_cost / open_qty
                pnl = closed * (float(price) - avg_entry)
                out.append(
                    RoundTrip(
                        ticker=ticker,
                        entry_at=opened_at or leg["placed_at"],
                        exit_at=leg["placed_at"],
                        qty=round(closed, 6),
                        entry_price=round(avg_entry, 4),
                        exit_price=round(float(price), 4),
                        pnl=round(pnl, 2),
                        return_pct=round((float(price) / avg_entry - 1) * 100, 2),
                        exit_reason=leg["reason"] or "unknown",
                    )
                )
                open_cost -= closed * avg_entry
                open_qty -= closed
                if open_qty <= 1e-9:
                    open_qty, open_cost, opened_at = 0.0, 0.0, None

    out.sort(key=lambda t: t.exit_at)
    return out


def realized_stats(trips: list[RoundTrip]) -> dict:
    """Headline metrics over closed round trips."""
    if not trips:
        return {"closed_trades": 0}

    wins = [t for t in trips if t.pnl > 0]
    losses = [t for t in trips if t.pnl <= 0]
    total_pnl = sum(t.pnl for t in trips)
    avg_win = sum(t.pnl for t in wins) / len(wins) if wins else 0.0
    avg_loss = sum(t.pnl for t in losses) / len(losses) if losses else 0.0
    holds = [t.hold_days for t in trips if t.hold_days is not None]

    gross_win = sum(t.pnl for t in wins)
    gross_loss = abs(sum(t.pnl for t in losses))

    return {
        "closed_trades": len(trips),
        "wins": len(wins),
        "losses": len(losses),
        "win_rate_pct": round(len(wins) / len(trips) * 100, 1),
        "realized_pnl": round(total_pnl, 2),
        "avg_win": round(avg_win, 2),
        "avg_loss": round(avg_loss, 2),
        # The number that decides whether the win rate means anything.
        "expectancy_per_trade": round(total_pnl / len(trips), 2),
        "profit_factor": round(gross_win / gross_loss, 2) if gross_loss > 0 else None,
        "avg_hold_days": round(sum(holds) / len(holds), 1) if holds else None,
        "best": max(trips, key=lambda t: t.pnl).ticker if trips else None,
        "worst": min(trips, key=lambda t: t.pnl).ticker if trips else None,
        "exits_by_reason": _count(t.exit_reason for t in trips),
    }


def _count(items) -> dict[str, int]:
    out: dict[str, int] = {}
    for i in items:
        out[i] = out.get(i, 0) + 1
    return out


def signal_funnel(conn: sqlite3.Connection) -> dict:
    """Counts by signal status, plus how many filings have been ingested."""
    cur = conn.execute("SELECT status, COUNT(*) AS n FROM signals GROUP BY status")
    by_status = {r["status"]: r["n"] for r in cur.fetchall()}
    processed = conn.execute("SELECT COUNT(*) AS n FROM processed_filings").fetchone()["n"]
    return {
        "filings_processed": processed,
        "signals_total": sum(by_status.values()),
        "by_status": by_status,
    }


def open_positions(conn: sqlite3.Connection, market=None) -> list[dict]:
    """Open positions, marked to market when a quote is reachable.

    ``market`` is any object with ``latest_price(ticker)``. When it is absent or
    a lookup returns None, the mark is reported as ``unavailable`` — never
    silently substituted with the entry price, which would show a real loss as
    a flat position.
    """
    cur = conn.execute("SELECT * FROM positions WHERE status = 'open' ORDER BY ticker")
    rows = []
    for r in cur.fetchall():
        entry, qty = float(r["entry_price"]), float(r["qty"])
        item = {
            "ticker": r["ticker"],
            "qty": qty,
            "entry_price": round(entry, 4),
            "entry_at": r["entry_at"],
            "high_water_mark": round(float(r["high_water_mark"]), 4),
            "mark": "unavailable",
            "unrealized_pnl": None,
            "unrealized_pct": None,
        }
        if market is not None:
            px = market.latest_price(r["ticker"])
            if px is not None and entry > 0:
                item["mark"] = round(float(px), 4)
                item["unrealized_pnl"] = round(qty * (float(px) - entry), 2)
                item["unrealized_pct"] = round((float(px) / entry - 1) * 100, 2)
        rows.append(item)
    return rows


def build_report(conn: sqlite3.Connection, market=None) -> dict:
    """Assemble the full scorecard."""
    trades = conn.execute("SELECT * FROM trades ORDER BY id ASC").fetchall()
    trips = round_trips(trades)
    positions = open_positions(conn, market)

    marked = [p for p in positions if p["unrealized_pnl"] is not None]
    unrealized = round(sum(p["unrealized_pnl"] for p in marked), 2) if marked else None

    return {
        "realized": realized_stats(trips),
        "open_positions": positions,
        "unrealized_pnl": unrealized,
        "positions_unmarked": len(positions) - len(marked),
        "signal_funnel": signal_funnel(conn),
        "order_legs_logged": len(trades),
        "round_trips": [t.__dict__ | {"hold_days": t.hold_days} for t in trips],
    }


def format_report(rep: dict) -> str:
    """Human-readable scorecard."""
    r = rep["realized"]
    out: list[str] = ["", "=== Realized (closed round trips) ==="]

    if not r.get("closed_trades"):
        out.append("  no closed trades yet")
    else:
        out.append(f"  closed trades:   {r['closed_trades']}  ({r['wins']}W / {r['losses']}L)")
        out.append(f"  win rate:        {r['win_rate_pct']}%")
        out.append(f"  realized P/L:    ${r['realized_pnl']:,.2f}")
        out.append(f"  avg win:         ${r['avg_win']:,.2f}")
        out.append(f"  avg loss:        ${r['avg_loss']:,.2f}")
        out.append(f"  expectancy:      ${r['expectancy_per_trade']:,.2f} per trade")
        pf = r["profit_factor"]
        out.append(f"  profit factor:   {pf if pf is not None else 'n/a (no losses yet)'}")
        out.append(f"  avg hold:        {r['avg_hold_days']} days")
        out.append(f"  exits:           {r['exits_by_reason']}")
        # Win rate without expectancy is the exact shape of an advertisement.
        if r["expectancy_per_trade"] <= 0 < r["win_rate_pct"]:
            out.append(
                f"  NOTE: {r['win_rate_pct']}% of trades won but expectancy is "
                f"${r['expectancy_per_trade']:,.2f} — the losers are bigger than the winners."
            )

    out.append("")
    out.append("=== Open positions ===")
    if not rep["open_positions"]:
        out.append("  none")
    for p in rep["open_positions"]:
        if p["unrealized_pnl"] is None:
            out.append(
                f"  {p['ticker']:<8} qty={p['qty']:<10.4f} entry=${p['entry_price']:<9.2f} "
                f"mark=UNAVAILABLE (market data unreachable)"
            )
        else:
            out.append(
                f"  {p['ticker']:<8} qty={p['qty']:<10.4f} entry=${p['entry_price']:<9.2f} "
                f"mark=${p['mark']:<9.2f} P/L=${p['unrealized_pnl']:+,.2f} "
                f"({p['unrealized_pct']:+.2f}%)"
            )
    if rep["positions_unmarked"]:
        out.append(
            f"  {rep['positions_unmarked']} position(s) could not be marked — "
            "unrealized P/L is incomplete."
        )
    elif rep["unrealized_pnl"] is not None:
        out.append(f"  total unrealized: ${rep['unrealized_pnl']:+,.2f}")

    f = rep["signal_funnel"]
    out.append("")
    out.append("=== Signal funnel ===")
    out.append(f"  filings processed: {f['filings_processed']}")
    out.append(f"  signals qualified: {f['signals_total']}")
    out.append(f"  by status:         {f['by_status'] or '{}'}")
    out.append(f"  order legs logged: {rep['order_legs_logged']}")
    out.append("")
    return "\n".join(out)
