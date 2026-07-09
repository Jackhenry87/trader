"""Read/write helpers over the SQLite state DB.

Thin, explicit functions — no ORM magic. Every write is committed immediately so
a crash mid-job never loses a recorded fill or a processed-filing marker.
"""

from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from datetime import UTC, datetime

from src.signals.models import Signal


def _now_iso() -> str:
    return datetime.now(UTC).isoformat()


@dataclass
class PositionRow:
    ticker: str
    entry_price: float
    qty: float
    entry_at: str
    high_water_mark: float
    status: str


class Repo:
    """Repository object bound to a single SQLite connection."""

    def __init__(self, conn: sqlite3.Connection) -> None:
        self.conn = conn

    # --- processed filings ---------------------------------------------------
    def is_filing_processed(self, accession_no: str) -> bool:
        cur = self.conn.execute(
            "SELECT 1 FROM processed_filings WHERE accession_no = ?", (accession_no,)
        )
        return cur.fetchone() is not None

    def mark_filing_processed(self, accession_no: str, form_type: str = "4") -> None:
        self.conn.execute(
            "INSERT OR IGNORE INTO processed_filings(accession_no, form_type, seen_at) "
            "VALUES (?, ?, ?)",
            (accession_no, form_type, _now_iso()),
        )
        self.conn.commit()

    # --- signals -------------------------------------------------------------
    def queue_signal(self, signal: Signal) -> int:
        cur = self.conn.execute(
            "INSERT INTO signals(ticker, issuer_cik, kind, qualified_at, status, detail_json) "
            "VALUES (?, ?, ?, ?, 'queued', ?)",
            (
                signal.ticker,
                signal.issuer_cik,
                signal.kind.value,
                signal.qualified_at.isoformat(),
                json.dumps(signal.detail()),
            ),
        )
        self.conn.commit()
        return int(cur.lastrowid)

    def queued_signals(self) -> list[sqlite3.Row]:
        cur = self.conn.execute("SELECT * FROM signals WHERE status = 'queued' ORDER BY id ASC")
        return cur.fetchall()

    def set_signal_status(self, signal_id: int, status: str) -> None:
        self.conn.execute("UPDATE signals SET status = ? WHERE id = ?", (status, signal_id))
        self.conn.commit()

    def has_queued_signal_for(self, ticker: str) -> bool:
        cur = self.conn.execute(
            "SELECT 1 FROM signals WHERE ticker = ? AND status = 'queued'", (ticker.upper(),)
        )
        return cur.fetchone() is not None

    # --- positions -----------------------------------------------------------
    def upsert_position(
        self,
        ticker: str,
        entry_price: float,
        qty: float,
        high_water_mark: float | None = None,
        entry_at: str | None = None,
        status: str = "open",
    ) -> None:
        hwm = high_water_mark if high_water_mark is not None else entry_price
        self.conn.execute(
            "INSERT INTO positions(ticker, entry_price, qty, entry_at, high_water_mark, status) "
            "VALUES (?, ?, ?, ?, ?, ?) "
            "ON CONFLICT(ticker) DO UPDATE SET "
            "  entry_price=excluded.entry_price, qty=excluded.qty, "
            "  high_water_mark=excluded.high_water_mark, status=excluded.status",
            (ticker.upper(), entry_price, qty, entry_at or _now_iso(), hwm, status),
        )
        self.conn.commit()

    def update_high_water_mark(self, ticker: str, hwm: float) -> None:
        self.conn.execute(
            "UPDATE positions SET high_water_mark = ? WHERE ticker = ?",
            (hwm, ticker.upper()),
        )
        self.conn.commit()

    def close_position(self, ticker: str) -> None:
        self.conn.execute(
            "UPDATE positions SET status = 'closed' WHERE ticker = ?", (ticker.upper(),)
        )
        self.conn.commit()

    def get_position(self, ticker: str) -> PositionRow | None:
        cur = self.conn.execute("SELECT * FROM positions WHERE ticker = ?", (ticker.upper(),))
        row = cur.fetchone()
        return _to_position(row) if row else None

    def open_positions(self) -> list[PositionRow]:
        cur = self.conn.execute("SELECT * FROM positions WHERE status = 'open' ORDER BY ticker ASC")
        return [_to_position(r) for r in cur.fetchall()]

    def open_position_tickers(self) -> set[str]:
        return {p.ticker for p in self.open_positions()}

    # --- trades --------------------------------------------------------------
    def log_trade(
        self,
        ticker: str,
        side: str,
        qty: float | None,
        price: float | None,
        notional: float | None,
        order_id: str | None,
        reason: str,
    ) -> int:
        cur = self.conn.execute(
            "INSERT INTO trades(ticker, side, qty, price, notional, placed_at, order_id, reason) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (ticker.upper(), side, qty, price, notional, _now_iso(), order_id, reason),
        )
        self.conn.commit()
        return int(cur.lastrowid)

    def trades_for(self, ticker: str) -> list[sqlite3.Row]:
        cur = self.conn.execute(
            "SELECT * FROM trades WHERE ticker = ? ORDER BY id ASC", (ticker.upper(),)
        )
        return cur.fetchall()


def _to_position(row: sqlite3.Row) -> PositionRow:
    return PositionRow(
        ticker=row["ticker"],
        entry_price=row["entry_price"],
        qty=row["qty"],
        entry_at=row["entry_at"],
        high_water_mark=row["high_water_mark"],
        status=row["status"],
    )
