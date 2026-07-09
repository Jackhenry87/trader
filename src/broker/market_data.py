"""Market data for the liquidity screen and pricing.

Uses alpaca-py's ``StockHistoricalDataClient`` (free IEX feed is fine for paper).
Provides: latest trade price, and an average daily dollar-volume estimate over a
trailing window for the liquidity screen.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from config.settings import Settings, get_settings
from src.notify.notifier import get_logger

_log = get_logger("market_data")


@dataclass(frozen=True)
class LiquiditySnapshot:
    """Latest price and trailing average dollar volume for one symbol."""

    ticker: str
    price: float | None
    avg_dollar_volume: float | None


class MarketData:
    """Wrapper over alpaca-py historical data + latest quote."""

    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or get_settings()
        from alpaca.data.historical import StockHistoricalDataClient

        self._client = StockHistoricalDataClient(
            api_key=self.settings.alpaca_api_key,
            secret_key=self.settings.alpaca_secret_key,
        )
        self._feed = self._resolve_feed(self.settings.alpaca_data_feed)

    @staticmethod
    def _resolve_feed(name: str):
        """Map the configured feed name to alpaca-py's DataFeed enum.

        Free/paper plans only include IEX; SIP requires a paid subscription and
        otherwise fails with "subscription does not permit querying SIP data".
        """
        from alpaca.data.enums import DataFeed

        return {"iex": DataFeed.IEX, "sip": DataFeed.SIP}.get(name.lower(), DataFeed.IEX)

    def latest_price(self, ticker: str) -> float | None:
        """Latest trade price, or None if unavailable."""
        from alpaca.data.requests import StockLatestTradeRequest

        try:
            req = StockLatestTradeRequest(symbol_or_symbols=ticker, feed=self._feed)
            resp = self._client.get_stock_latest_trade(req)
            trade = resp.get(ticker)
            return float(trade.price) if trade else None
        except Exception as exc:  # noqa: BLE001
            _log.warning("latest_price_failed", ticker=ticker, error=str(exc))
            return None

    def liquidity(self, ticker: str, lookback_days: int = 30) -> LiquiditySnapshot:
        """Compute latest price + trailing average daily dollar volume.

        Average dollar volume = mean of (close * volume) over the daily bars in
        the lookback window. Used by the liquidity screen.
        """
        from alpaca.data.requests import StockBarsRequest
        from alpaca.data.timeframe import TimeFrame

        end = datetime.now(UTC)
        start = end - timedelta(days=lookback_days * 2)  # pad for weekends/holidays
        try:
            req = StockBarsRequest(
                symbol_or_symbols=ticker,
                timeframe=TimeFrame.Day,
                start=start,
                end=end,
                feed=self._feed,
            )
            bars = self._client.get_stock_bars(req)
            data = bars.data.get(ticker, []) if hasattr(bars, "data") else []
        except Exception as exc:  # noqa: BLE001
            _log.warning("liquidity_bars_failed", ticker=ticker, error=str(exc))
            return LiquiditySnapshot(ticker, None, None)

        if not data:
            return LiquiditySnapshot(ticker, None, None)

        recent = data[-lookback_days:]
        dollar_vols = [float(b.close) * float(b.volume) for b in recent if b.volume]
        price = float(data[-1].close)
        avg_dv = sum(dollar_vols) / len(dollar_vols) if dollar_vols else None
        return LiquiditySnapshot(ticker, price, avg_dv)
