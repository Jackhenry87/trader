"""Dataclasses for the signal pipeline: raw insider buys and qualified signals."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime
from enum import StrEnum


class SignalKind(StrEnum):
    """Why a signal qualified."""

    SIZE = "size"  # A single insider's buy cleared the dollar threshold.
    CLUSTER = "cluster"  # Multiple insiders bought the same issuer in the window.


@dataclass(frozen=True)
class InsiderBuy:
    """A single open-market purchase (transaction code ``P``) from a Form 4.

    One Form 4 can contain several transactions; this represents exactly one
    non-derivative ``P`` line item, already filtered to purchases.
    """

    accession_no: str
    issuer_cik: str
    issuer_name: str
    ticker: str | None
    owner_name: str
    owner_is_officer: bool
    owner_is_director: bool
    owner_is_ten_pct: bool
    transaction_date: date
    shares: float
    price_per_share: float
    filed_at: datetime

    @property
    def value_usd(self) -> float:
        """Dollar value of this single purchase."""
        return self.shares * self.price_per_share

    @property
    def owner_relationship(self) -> str:
        """Human-readable role summary, e.g. ``officer,director``."""
        roles = []
        if self.owner_is_officer:
            roles.append("officer")
        if self.owner_is_director:
            roles.append("director")
        if self.owner_is_ten_pct:
            roles.append("10pct")
        return ",".join(roles) if roles else "unknown"


@dataclass
class Signal:
    """A qualified entry signal for one ticker, ready for sizing + execution."""

    ticker: str
    issuer_cik: str
    issuer_name: str
    kind: SignalKind
    qualified_at: datetime
    # The insider buys that produced this signal (1 for SIZE, >=2 for CLUSTER).
    buys: list[InsiderBuy] = field(default_factory=list)

    @property
    def total_value_usd(self) -> float:
        return sum(b.value_usd for b in self.buys)

    @property
    def distinct_insiders(self) -> int:
        return len({b.owner_name.strip().lower() for b in self.buys})

    @property
    def accession_numbers(self) -> list[str]:
        return sorted({b.accession_no for b in self.buys})

    def detail(self) -> dict:
        """A JSON-serializable summary persisted alongside the signal."""
        return {
            "kind": self.kind.value,
            "ticker": self.ticker,
            "issuer_cik": self.issuer_cik,
            "issuer_name": self.issuer_name,
            "total_value_usd": round(self.total_value_usd, 2),
            "distinct_insiders": self.distinct_insiders,
            "accession_numbers": self.accession_numbers,
            "owners": sorted({b.owner_name for b in self.buys}),
        }
