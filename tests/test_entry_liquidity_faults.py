"""A broken market-data feed must be loud, not silent.

Before this, ``MarketData.liquidity`` returned ``(None, None)`` both when the
lookup failed and when the name was genuinely thin. ``passes_liquidity`` turned
each into a routine info-level rejection, so an outage — bad Alpaca keys, an
unentitled SIP feed, a network fault — muted every signal and the run reported
"0 queued", which is exactly what a quiet day looks like.

These tests pin the distinction end-to-end through ``gather_and_queue``.
"""

from __future__ import annotations

import pytest

from src.broker.market_data import LiquiditySnapshot
from src.execution.entry import gather_and_queue
from tests.conftest import make_buy


class FakeRepo:
    def __init__(self) -> None:
        self.queued: list[str] = []

    def has_queued_signal_for(self, ticker: str) -> bool:
        return False

    def queue_signal(self, sig) -> None:
        self.queued.append(sig.ticker)


class FakeMarket:
    """Returns a preset snapshot per ticker."""

    def __init__(self, snaps: dict[str, LiquiditySnapshot]) -> None:
        self._snaps = snaps

    def liquidity(self, ticker: str) -> LiquiditySnapshot:
        return self._snaps[ticker]


@pytest.fixture
def captured_events(monkeypatch) -> list[tuple[str, str, dict]]:
    """Capture every notify() call as (event, level, fields)."""
    events: list[tuple[str, str, dict]] = []

    def fake_notify(event: str, level: str = "info", slack: bool = False, **fields):
        events.append((event, level, fields))

    monkeypatch.setattr("src.execution.entry.notify", fake_notify)
    return events


def _qualifying_buys(ticker: str):
    """Two distinct insiders -> CLUSTER qualification, independent of size."""
    return [
        make_buy(ticker, "Alice", shares=2000, price=30.0),
        make_buy(ticker, "Bob", shares=2000, price=30.0),
    ]


def test_data_fault_escalates_to_error_and_emits_summary(settings, captured_events):
    market = FakeMarket({"AAA": LiquiditySnapshot("AAA", None, None, error="401 unauthorized")})
    repo = FakeRepo()

    queued = gather_and_queue(_qualifying_buys("AAA"), settings, repo, market, set(), set())

    assert queued == []
    assert repo.queued == []

    # The per-signal rejection is loud, and names the cause.
    rejections = [e for e in captured_events if e[0] == "signal_rejected"]
    assert len(rejections) == 1
    _, level, fields = rejections[0]
    assert level == "error", "a data fault must reach the Slack sink (warning+)"
    assert fields["reason"].startswith("data_unavailable")
    assert "401 unauthorized" in fields["reason"]

    # And the run emits an explicit outage summary rather than ending quietly.
    summaries = [e for e in captured_events if e[0] == "liquidity_data_unavailable"]
    assert len(summaries) == 1
    _, level, fields = summaries[0]
    assert level == "error"
    assert fields["tickers"] == ["AAA"]
    assert fields["dropped"] == 1
    assert fields["queued"] == 0


def test_genuinely_thin_name_stays_quiet(settings, captured_events):
    """A real liquidity rejection must NOT trip the outage alarm."""
    market = FakeMarket({"BBB": LiquiditySnapshot("BBB", 10.0, 500_000.0)})
    repo = FakeRepo()

    queued = gather_and_queue(_qualifying_buys("BBB"), settings, repo, market, set(), set())

    assert queued == []
    rejections = [e for e in captured_events if e[0] == "signal_rejected"]
    assert len(rejections) == 1
    _, level, fields = rejections[0]
    assert level == "info", "an illiquid name is routine, not an incident"
    assert "illiquid" in fields["reason"]

    assert not [e for e in captured_events if e[0] == "liquidity_data_unavailable"]


def test_empty_feed_response_is_a_rejection_not_a_fault(settings, captured_events):
    """Feed answered with no bars: reject the name, but don't cry outage."""
    market = FakeMarket({"CCC": LiquiditySnapshot("CCC", None, None)})
    repo = FakeRepo()

    gather_and_queue(_qualifying_buys("CCC"), settings, repo, market, set(), set())

    _, level, fields = [e for e in captured_events if e[0] == "signal_rejected"][0]
    assert level == "info"
    assert fields["reason"] == "no_price"
    assert not [e for e in captured_events if e[0] == "liquidity_data_unavailable"]


def test_outage_summary_reports_partial_success(settings, captured_events):
    """Good names still queue; the summary scopes the damage to the bad ones."""
    market = FakeMarket(
        {
            "GOOD": LiquiditySnapshot("GOOD", 25.0, 9_000_000.0),
            "DEAD": LiquiditySnapshot("DEAD", None, None, error="connection reset"),
        }
    )
    repo = FakeRepo()

    queued = gather_and_queue(
        _qualifying_buys("GOOD") + _qualifying_buys("DEAD"),
        settings,
        repo,
        market,
        set(),
        set(),
    )

    assert [s.ticker for s in queued] == ["GOOD"]
    _, _, fields = [e for e in captured_events if e[0] == "liquidity_data_unavailable"][0]
    assert fields["tickers"] == ["DEAD"]
    assert fields["dropped"] == 1
    assert fields["queued"] == 1
    assert fields["considered"] == 2


def test_snapshot_data_unavailable_flag():
    assert LiquiditySnapshot("X", None, None, error="boom").data_unavailable is True
    assert LiquiditySnapshot("X", None, None).data_unavailable is False
    assert LiquiditySnapshot("X", 10.0, 1e7).data_unavailable is False
