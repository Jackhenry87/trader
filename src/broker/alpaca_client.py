"""Thin, paper-gated wrapper over alpaca-py's TradingClient.

Everything that talks to the broker goes through here so the paper assertion and
dry-run gate live in one place. We use the *current* official SDK (``alpaca-py``),
never the deprecated ``alpaca-trade-api``.
"""

from __future__ import annotations

from dataclasses import dataclass

from config.settings import Settings, get_settings
from src.broker.request_id import RequestIdTracker, attach_request_id_capture
from src.notify.notifier import get_logger
from src.risk.guards import AccountSnapshot, assert_paper

_log = get_logger("alpaca")


@dataclass
class OrderResult:
    """Normalized result of an entry/exit order placement."""

    ticker: str
    side: str
    order_id: str | None
    notional: float | None
    qty: float | None
    status: str
    dry_run: bool


class AlpacaBroker:
    """Wrapper over alpaca-py TradingClient, hard-gated to paper by default."""

    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or get_settings()
        # Import inside __init__ so unit tests that never construct a broker do
        # not require alpaca-py to be installed.
        from alpaca.trading.client import TradingClient

        self.settings.assert_paper_or_live_ok()
        self.settings.require_alpaca_keys()

        paper = self.settings.is_paper
        self._client = TradingClient(
            api_key=self.settings.alpaca_api_key,
            secret_key=self.settings.alpaca_secret_key,
            paper=paper,
        )
        # Capture Alpaca's X-Request-ID on every call so we can quote it in
        # support tickets (Alpaca can't look these up after the fact).
        self.request_ids = RequestIdTracker()
        session = getattr(self._client, "_session", None)
        if session is not None:
            attach_request_id_capture(session, self.request_ids, _log)
        # Belt and suspenders: assert the resolved account is paper.
        self._assert_paper_account(paper)
        _log.info("alpaca_connected", paper=paper, base_url=self.settings.alpaca_base_url)

    @property
    def last_request_id(self) -> str | None:
        """Most recent Alpaca X-Request-ID — include this in support tickets."""
        return self.request_ids.last

    def _assert_paper_account(self, paper_flag: bool) -> None:
        assert_paper(is_paper=paper_flag, live_enabled=self.settings.live_enabled)

    # --- account / clock -----------------------------------------------------
    def get_account(self):
        return self._client.get_account()

    def snapshot(self) -> AccountSnapshot:
        acct = self.get_account()
        positions = self._client.get_all_positions()
        return AccountSnapshot(
            equity=float(acct.equity),
            last_equity=float(acct.last_equity),
            cash=float(acct.cash),
            open_positions=len(positions),
            is_paper=self.settings.is_paper,
        )

    def get_clock(self):
        return self._client.get_clock()

    def is_market_open(self) -> bool:
        return bool(self.get_clock().is_open)

    def get_positions(self) -> list:
        return self._client.get_all_positions()

    def get_position_symbols(self) -> set[str]:
        return {p.symbol.upper() for p in self._client.get_all_positions()}

    def get_open_orders(self) -> list:
        from alpaca.trading.enums import QueryOrderStatus
        from alpaca.trading.requests import GetOrdersRequest

        req = GetOrdersRequest(status=QueryOrderStatus.OPEN)
        return self._client.get_orders(filter=req)

    def open_order_symbols(self) -> set[str]:
        return {o.symbol.upper() for o in self.get_open_orders()}

    # --- orders --------------------------------------------------------------
    def place_notional_buy(self, ticker: str, notional: float) -> OrderResult:
        """Place (or, in dry-run, log) a notional market buy at next open.

        Notional orders are market/day and support fractional shares — exactly
        what we want to split $200 across names. Nothing is placed when
        ``DRY_RUN`` is true.
        """
        if self.settings.dry_run:
            _log.info("dry_run_would_buy", ticker=ticker, notional=round(notional, 2), side="buy")
            return OrderResult(ticker, "buy", None, notional, None, "dry_run", True)

        from alpaca.trading.enums import OrderSide, TimeInForce
        from alpaca.trading.requests import MarketOrderRequest

        req = MarketOrderRequest(
            symbol=ticker,
            notional=round(notional, 2),
            side=OrderSide.BUY,
            time_in_force=TimeInForce.DAY,
        )
        try:
            order = self._client.submit_order(req)
        except Exception as exc:  # noqa: BLE001 — annotate with Request ID, re-raise.
            _log.error(
                "order_submit_failed",
                ticker=ticker,
                notional=round(notional, 2),
                side="buy",
                error=str(exc),
                request_id=self.last_request_id,
            )
            raise
        _log.info(
            "order_submitted",
            ticker=ticker,
            notional=round(notional, 2),
            side="buy",
            order_id=str(order.id),
            status=str(order.status),
            request_id=self.last_request_id,
        )
        return OrderResult(ticker, "buy", str(order.id), notional, None, str(order.status), False)

    def close_position(self, ticker: str, reason: str) -> OrderResult:
        """Liquidate an entire position at market (or log it in dry-run)."""
        if self.settings.dry_run:
            _log.info("dry_run_would_sell", ticker=ticker, reason=reason, side="sell")
            return OrderResult(ticker, "sell", None, None, None, "dry_run", True)

        try:
            order = self._client.close_position(ticker)
        except Exception as exc:  # noqa: BLE001 — annotate with Request ID, re-raise.
            _log.error(
                "position_close_failed",
                ticker=ticker,
                reason=reason,
                error=str(exc),
                request_id=self.last_request_id,
            )
            raise
        _log.info(
            "position_closed",
            ticker=ticker,
            reason=reason,
            order_id=str(order.id),
            status=str(order.status),
            request_id=self.last_request_id,
        )
        return OrderResult(ticker, "sell", str(order.id), None, None, str(order.status), False)
