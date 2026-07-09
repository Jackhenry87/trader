"""Filter tests: cluster detection, size threshold, liquidity, dedupe."""

from __future__ import annotations

from datetime import date

from src.signals.filters import (
    dedupe_against_holdings,
    passes_liquidity,
    qualify_signals,
)
from src.signals.models import SignalKind
from tests.conftest import make_buy


def test_size_signal_single_large_buy(settings):
    # One insider buys $60k worth -> clears the $50k size threshold.
    buys = [make_buy("BIG", "Alice", shares=2000, price=30.0)]  # $60,000
    signals = qualify_signals(buys, settings)
    assert len(signals) == 1
    assert signals[0].kind == SignalKind.SIZE
    assert signals[0].ticker == "BIG"


def test_small_single_buy_does_not_qualify(settings):
    # $10k single buy, only one insider -> neither size nor cluster.
    buys = [make_buy("SMALL", "Bob", shares=400, price=25.0)]  # $10,000
    assert qualify_signals(buys, settings) == []


def test_cluster_of_two_insiders_qualifies(settings):
    # Two distinct insiders, each below the size threshold, same issuer, in window.
    buys = [
        make_buy("CLUS", "Alice", shares=200, price=25.0, txn_date=date(2024, 5, 10)),  # $5k
        make_buy("CLUS", "Bob", shares=200, price=25.0, txn_date=date(2024, 5, 12)),  # $5k
    ]
    signals = qualify_signals(buys, settings)
    assert len(signals) == 1
    assert signals[0].kind == SignalKind.CLUSTER
    assert signals[0].distinct_insiders == 2


def test_two_buys_same_insider_is_not_a_cluster(settings):
    # Same person twice -> one distinct insider -> no cluster; sizes too small.
    buys = [
        make_buy("SAME", "Alice", shares=200, price=25.0, txn_date=date(2024, 5, 10)),
        make_buy("SAME", "Alice", shares=200, price=25.0, txn_date=date(2024, 5, 11)),
    ]
    assert qualify_signals(buys, settings) == []


def test_cluster_outside_window_does_not_qualify(settings):
    # Two insiders but 10 calendar days apart > 5-day window.
    buys = [
        make_buy("WIDE", "Alice", shares=200, price=25.0, txn_date=date(2024, 5, 1)),
        make_buy("WIDE", "Bob", shares=200, price=25.0, txn_date=date(2024, 5, 15)),
    ]
    assert qualify_signals(buys, settings) == []


def test_cluster_labeled_cluster_even_when_size_also_qualifies(settings):
    # Both a big single buy and a second insider -> labeled CLUSTER (stronger).
    buys = [
        make_buy("BOTH", "Alice", shares=2000, price=30.0),  # $60k, size qualifies
        make_buy("BOTH", "Bob", shares=100, price=30.0),  # adds a distinct insider
    ]
    signals = qualify_signals(buys, settings)
    assert len(signals) == 1
    assert signals[0].kind == SignalKind.CLUSTER


def test_liquidity_screen():
    from config.settings import Settings

    s = Settings(min_price=5.0, min_avg_dollar_volume=1_000_000.0)
    assert passes_liquidity(10.0, 5_000_000, s) == (True, None)
    ok, reason = passes_liquidity(3.0, 5_000_000, s)
    assert ok is False and "price_below_min" in reason
    ok, reason = passes_liquidity(10.0, 500_000, s)
    assert ok is False and "illiquid" in reason
    assert passes_liquidity(None, 5_000_000, s)[0] is False
    assert passes_liquidity(10.0, None, s)[0] is False


def test_dedupe_against_holdings(settings):
    buys = [
        make_buy("HELD", "Alice", shares=2000, price=30.0),
        make_buy("PEND", "Bob", shares=2000, price=30.0),
        make_buy("NEW", "Carol", shares=2000, price=30.0),
    ]
    signals = qualify_signals(buys, settings)
    kept, rejected = dedupe_against_holdings(
        signals, held_tickers={"HELD"}, open_order_tickers={"PEND"}
    )
    kept_tickers = {s.ticker for s in kept}
    assert kept_tickers == {"NEW"}
    reasons = {s.ticker: r for s, r in rejected}
    assert reasons["HELD"] == "already_held"
    assert reasons["PEND"] == "open_entry_order"
