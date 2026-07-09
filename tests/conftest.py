"""Shared test fixtures."""

from __future__ import annotations

from datetime import UTC, date, datetime

import pytest

from config.settings import Settings
from src.signals.models import InsiderBuy


@pytest.fixture
def settings() -> Settings:
    """Default settings with the spec's $200 defaults, dry-run + paper."""
    return Settings(
        dry_run=True,
        allow_live=False,
        confirm_live=False,
        alpaca_base_url="https://paper-api.alpaca.markets",
        starting_equity=200.0,
        dollars_per_position=25.0,
        max_open_positions=8,
        max_daily_loss_pct=10.0,
        min_insider_buy_usd=50_000.0,
        cluster_min_insiders=2,
        cluster_window_days=5,
        min_price=5.0,
        min_avg_dollar_volume=1_000_000.0,
        trail_pct=10.0,
        hard_stop_pct=15.0,
        max_hold_days=20,
        max_position_equity_pct=20.0,
    )


def make_buy(
    ticker: str,
    owner: str,
    shares: float,
    price: float,
    txn_date: date | None = None,
    accession: str | None = None,
) -> InsiderBuy:
    txn_date = txn_date or date(2024, 5, 10)
    return InsiderBuy(
        accession_no=accession or f"{ticker}-{owner}-{txn_date}",
        issuer_cik="12345",
        issuer_name=f"{ticker} Inc",
        ticker=ticker,
        owner_name=owner,
        owner_is_officer=True,
        owner_is_director=False,
        owner_is_ten_pct=False,
        transaction_date=txn_date,
        shares=shares,
        price_per_share=price,
        filed_at=datetime(txn_date.year, txn_date.month, txn_date.day, tzinfo=UTC),
    )
