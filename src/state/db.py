"""SQLite connection + schema for persistent bot state.

State must survive restarts. The schema tracks which filings we've processed
(so we never double-count), qualified signals, open/closed positions, and a full
trade log.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

from config.settings import get_settings

SCHEMA = """
CREATE TABLE IF NOT EXISTS processed_filings (
    accession_no TEXT PRIMARY KEY,
    form_type    TEXT,
    seen_at      TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS signals (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    ticker       TEXT NOT NULL,
    issuer_cik   TEXT,
    kind         TEXT NOT NULL,
    qualified_at TEXT NOT NULL,
    status       TEXT NOT NULL DEFAULT 'queued',  -- queued | placed | skipped
    detail_json  TEXT
);

CREATE INDEX IF NOT EXISTS idx_signals_status ON signals(status);
CREATE INDEX IF NOT EXISTS idx_signals_ticker ON signals(ticker);

CREATE TABLE IF NOT EXISTS positions (
    ticker          TEXT PRIMARY KEY,
    entry_price     REAL NOT NULL,
    qty             REAL NOT NULL,
    entry_at        TEXT NOT NULL,
    high_water_mark REAL NOT NULL,
    status          TEXT NOT NULL DEFAULT 'open'  -- open | closed
);

CREATE TABLE IF NOT EXISTS trades (
    id        INTEGER PRIMARY KEY AUTOINCREMENT,
    ticker    TEXT NOT NULL,
    side      TEXT NOT NULL,          -- buy | sell
    qty       REAL,
    price     REAL,
    notional  REAL,
    placed_at TEXT NOT NULL,
    order_id  TEXT,
    reason    TEXT
);

CREATE INDEX IF NOT EXISTS idx_trades_ticker ON trades(ticker);
"""


def connect(db_path: str | None = None) -> sqlite3.Connection:
    """Open (creating if needed) the SQLite DB and ensure the schema exists."""
    path = db_path or get_settings().db_path
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL;")
    conn.execute("PRAGMA foreign_keys=ON;")
    init_schema(conn)
    return conn


def init_schema(conn: sqlite3.Connection) -> None:
    conn.executescript(SCHEMA)
    conn.commit()
