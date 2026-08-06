"""Scorecard: round-trip pairing, expectancy, and honest handling of missing marks."""

from __future__ import annotations

import pytest

from src.report import build_report, format_report, realized_stats, round_trips
from src.state.db import connect


@pytest.fixture
def conn():
    c = connect(":memory:")
    yield c
    c.close()


def add_leg(c, ticker, side, qty, price, reason, placed_at="2024-05-10T14:00:00+00:00"):
    c.execute(
        "INSERT INTO trades(ticker, side, qty, price, notional, placed_at, order_id, reason) "
        "VALUES (?,?,?,?,?,?,?,?)",
        (ticker, side, qty, price, (qty or 0) * (price or 0), placed_at, "oid", reason),
    )
    c.commit()


def add_position(c, ticker, entry_price, qty, hwm):
    c.execute(
        "INSERT INTO positions(ticker, entry_price, qty, entry_at, high_water_mark, status) "
        "VALUES (?,?,?,?,?,'open')",
        (ticker, entry_price, qty, "2024-05-10T14:00:00+00:00", hwm),
    )
    c.commit()


def rows(c):
    return c.execute("SELECT * FROM trades ORDER BY id ASC").fetchall()


class FakeMarket:
    def __init__(self, prices):
        self._p = prices

    def latest_price(self, ticker):
        return self._p.get(ticker)


# ── Pairing ──────────────────────────────────────────────────────────────────


def test_pairs_buy_and_sell_into_one_round_trip(conn):
    add_leg(conn, "AAA", "buy", 2.0, 10.0, "entry", "2024-05-10T14:00:00+00:00")
    add_leg(conn, "AAA", "sell", 2.0, 12.0, "trailing_stop", "2024-05-20T14:00:00+00:00")

    trips = round_trips(rows(conn))
    assert len(trips) == 1
    t = trips[0]
    assert (t.entry_price, t.exit_price, t.qty) == (10.0, 12.0, 2.0)
    assert t.pnl == pytest.approx(4.0)
    assert t.return_pct == pytest.approx(20.0)
    assert t.exit_reason == "trailing_stop"
    assert t.hold_days == 10


def test_open_position_is_not_counted_as_a_round_trip(conn):
    add_leg(conn, "AAA", "buy", 2.0, 10.0, "entry")
    assert round_trips(rows(conn)) == []


def test_handles_repeated_cycles_in_one_ticker(conn):
    add_leg(conn, "AAA", "buy", 1.0, 10.0, "entry", "2024-01-01T00:00:00+00:00")
    add_leg(conn, "AAA", "sell", 1.0, 11.0, "max_hold", "2024-01-05T00:00:00+00:00")
    add_leg(conn, "AAA", "buy", 1.0, 20.0, "entry", "2024-02-01T00:00:00+00:00")
    add_leg(conn, "AAA", "sell", 1.0, 18.0, "hard_stop", "2024-02-03T00:00:00+00:00")

    trips = round_trips(rows(conn))
    assert [t.pnl for t in trips] == [pytest.approx(1.0), pytest.approx(-2.0)]
    assert [t.exit_reason for t in trips] == ["max_hold", "hard_stop"]


def test_legs_without_price_are_skipped_not_counted_as_zero(conn):
    """A dry-run or unfilled leg has no price; counting it as $0 would be a lie."""
    add_leg(conn, "AAA", "buy", None, None, "dry_run")
    add_leg(conn, "AAA", "sell", None, None, "dry_run")
    assert round_trips(rows(conn)) == []


def test_partial_sell_closes_only_what_was_sold(conn):
    add_leg(conn, "AAA", "buy", 4.0, 10.0, "entry")
    add_leg(conn, "AAA", "sell", 1.0, 12.0, "partial")
    trips = round_trips(rows(conn))
    assert len(trips) == 1
    assert trips[0].qty == pytest.approx(1.0)
    assert trips[0].pnl == pytest.approx(2.0)


# ── Stats ────────────────────────────────────────────────────────────────────


def test_expectancy_exposes_a_high_win_rate_that_loses_money(conn):
    """Three small wins and one large loss: 75% win rate, negative expectancy."""
    for i, (buy, sell) in enumerate([(10.0, 11.0), (10.0, 11.0), (10.0, 11.0), (10.0, 4.0)]):
        add_leg(conn, f"T{i}", "buy", 1.0, buy, "entry")
        add_leg(conn, f"T{i}", "sell", 1.0, sell, "exit")

    s = realized_stats(round_trips(rows(conn)))
    assert s["win_rate_pct"] == 75.0
    assert s["realized_pnl"] == pytest.approx(-3.0)
    assert s["expectancy_per_trade"] < 0
    assert s["profit_factor"] < 1

    # The formatter must call this out rather than let 75% stand unqualified.
    rep = build_report(conn)
    assert "the losers are bigger than the winners" in format_report(rep)


def test_profit_factor_is_none_when_there_are_no_losses(conn):
    add_leg(conn, "AAA", "buy", 1.0, 10.0, "entry")
    add_leg(conn, "AAA", "sell", 1.0, 11.0, "exit")
    assert realized_stats(round_trips(rows(conn)))["profit_factor"] is None


def test_empty_state_reports_cleanly(conn):
    rep = build_report(conn)
    assert rep["realized"] == {"closed_trades": 0}
    text = format_report(rep)
    assert "no closed trades yet" in text
    assert "none" in text


# ── Marks ────────────────────────────────────────────────────────────────────


def test_positions_are_marked_when_quotes_are_available(conn):
    add_position(conn, "AAA", entry_price=10.0, qty=2.0, hwm=12.0)
    rep = build_report(conn, FakeMarket({"AAA": 13.0}))
    p = rep["open_positions"][0]
    assert p["mark"] == 13.0
    assert p["unrealized_pnl"] == pytest.approx(6.0)
    assert p["unrealized_pct"] == pytest.approx(30.0)
    assert rep["unrealized_pnl"] == pytest.approx(6.0)
    assert rep["positions_unmarked"] == 0


def test_unavailable_mark_is_reported_not_silently_flattened(conn):
    """A losing position must never display as flat because the quote failed."""
    add_position(conn, "AAA", entry_price=10.0, qty=2.0, hwm=12.0)
    rep = build_report(conn, FakeMarket({}))  # lookup returns None

    p = rep["open_positions"][0]
    assert p["mark"] == "unavailable"
    assert p["unrealized_pnl"] is None
    assert rep["unrealized_pnl"] is None
    assert rep["positions_unmarked"] == 1

    text = format_report(rep)
    assert "UNAVAILABLE" in text
    assert "unrealized P/L is incomplete" in text


def test_no_market_client_still_produces_a_report(conn):
    add_position(conn, "AAA", entry_price=10.0, qty=2.0, hwm=12.0)
    rep = build_report(conn, market=None)
    assert rep["open_positions"][0]["mark"] == "unavailable"
    assert rep["positions_unmarked"] == 1


# ── Funnel ───────────────────────────────────────────────────────────────────


def test_signal_funnel_counts_by_status(conn):
    for ticker, status in [("A", "queued"), ("B", "placed"), ("C", "placed"), ("D", "skipped")]:
        conn.execute(
            "INSERT INTO signals(ticker, issuer_cik, kind, qualified_at, status) "
            "VALUES (?,?,?,?,?)",
            (ticker, "1", "CLUSTER", "2024-05-10T00:00:00+00:00", status),
        )
    conn.execute(
        "INSERT INTO processed_filings(accession_no, form_type, seen_at) VALUES ('x','4','t')"
    )
    conn.commit()

    f = build_report(conn)["signal_funnel"]
    assert f["signals_total"] == 4
    assert f["by_status"] == {"queued": 1, "placed": 2, "skipped": 1}
    assert f["filings_processed"] == 1
