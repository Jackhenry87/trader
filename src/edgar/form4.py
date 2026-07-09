"""Fetch and parse SEC Form 4 filings, extracting open-market purchases.

Ingestion path (verified against live EDGAR responses during development):

1. Pull the EDGAR **daily index** for a date:
   ``https://www.sec.gov/Archives/edgar/daily-index/{YYYY}/QTR{n}/form.{YYYYMMDD}.idx``
   which lists every filing for that date, one per line, sorted by form type.
2. For each ``4`` / ``4/A`` entry, fetch the full-submission ``.txt`` and extract
   the embedded ``<ownershipDocument>`` XML block.
3. Parse the XML and keep only non-derivative transactions with code ``P``
   (open-market purchase). Everything else (S/A/M/G/F/C ...) is ignored.

The parser is defensive: Form 4 XML frequently has missing prices (gifts),
footnote-only values, and multiple reporting owners. We skip anything we can't
turn into a real dollar-valued purchase rather than guessing.
"""

from __future__ import annotations

import re
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from datetime import UTC, date, datetime

from src.edgar.client import EdgarClient
from src.notify.notifier import get_logger
from src.signals.models import InsiderBuy

_log = get_logger("form4")

# Only this transaction code is an open-market purchase / buy signal.
BUY_CODE = "P"

_OWNERSHIP_RE = re.compile(r"<ownershipDocument>.*?</ownershipDocument>", re.DOTALL | re.IGNORECASE)


@dataclass(frozen=True)
class FilingRef:
    """One row from the EDGAR daily index."""

    form_type: str
    company_name: str
    cik: str
    date_filed: date
    txt_path: str  # e.g. edgar/data/320193/0000320193-24-000001.txt

    @property
    def accession_no(self) -> str:
        """Accession number derived from the submission filename."""
        fname = self.txt_path.rsplit("/", 1)[-1]
        return fname.removesuffix(".txt")

    @property
    def txt_url(self) -> str:
        return f"https://www.sec.gov/Archives/{self.txt_path.lstrip('/')}"


def daily_index_url(day: date) -> str:
    """Build the form-sorted daily index URL for a date."""
    quarter = (day.month - 1) // 3 + 1
    return (
        f"https://www.sec.gov/Archives/edgar/daily-index/"
        f"{day.year}/QTR{quarter}/form.{day:%Y%m%d}.idx"
    )


def parse_daily_index(text: str, form_types: tuple[str, ...] = ("4", "4/A")) -> list[FilingRef]:
    """Parse a ``form.*.idx`` file into filing references, filtered by form type.

    The index has a header block, a dashed separator line, then whitespace-
    delimited rows: ``Form Type | Company Name | CIK | Date Filed | File Name``.
    Company names contain spaces, so we anchor on the leading form-type token and
    the trailing ``edgar/...`` path, and treat the middle as the company name.
    """
    wanted = {ft.upper() for ft in form_types}
    refs: list[FilingRef] = []
    started = False

    for line in text.splitlines():
        if not started:
            # The data region begins after the dashed separator line.
            if set(line.strip()) == {"-"} and line.strip():
                started = True
            continue

        line = line.rstrip()
        if not line:
            continue

        # The trailing token is the path; the leading token is the form type.
        parts = line.split()
        if len(parts) < 5:
            continue
        form_type = parts[0].upper()
        if form_type not in wanted:
            continue

        path = parts[-1]
        if not path.startswith("edgar/"):
            continue
        date_str = parts[-2]
        cik = parts[-3]
        # Everything between the form type and CIK is the company name.
        company = " ".join(parts[1:-3]).strip()

        filed = _parse_index_date(date_str)
        if filed is None:
            continue

        refs.append(
            FilingRef(
                form_type=form_type,
                company_name=company,
                cik=cik.lstrip("0") or "0",
                date_filed=filed,
                txt_path=path,
            )
        )
    return refs


def _parse_index_date(value: str) -> date | None:
    """Parse an EDGAR index 'Date Filed' cell.

    The daily index uses ``YYYYMMDD``; our test fixtures and some tooling use
    ``YYYY-MM-DD``. Accept both.
    """
    for fmt in ("%Y%m%d", "%Y-%m-%d"):
        try:
            return datetime.strptime(value, fmt).date()
        except ValueError:
            continue
    return None


def extract_ownership_xml(submission_txt: str) -> str | None:
    """Pull the ``<ownershipDocument>`` XML block out of a full submission."""
    match = _OWNERSHIP_RE.search(submission_txt)
    return match.group(0) if match else None


def _text(el: ET.Element | None) -> str | None:
    if el is None or el.text is None:
        return None
    val = el.text.strip()
    return val or None


def _value(parent: ET.Element | None, child: str) -> str | None:
    """Read ``<child><value>...</value></child>`` (or a bare ``<child>``)."""
    if parent is None:
        return None
    node = parent.find(child)
    if node is None:
        return None
    value_node = node.find("value")
    if value_node is not None:
        return _text(value_node)
    return _text(node)


def _as_bool(val: str | None) -> bool:
    return str(val).strip().lower() in {"1", "true", "y", "yes"}


def parse_form4_xml(
    xml: str, accession_no: str, filed_at: datetime | None = None
) -> list[InsiderBuy]:
    """Parse Form 4 ownership XML into a list of open-market (``P``) buys.

    Returns one :class:`InsiderBuy` per qualifying non-derivative ``P``
    transaction. Non-purchase codes and unparseable/zero-value rows are skipped.
    """
    try:
        root = ET.fromstring(xml)
    except ET.ParseError as exc:
        _log.warning("form4_xml_parse_error", accession_no=accession_no, error=str(exc))
        return []

    issuer = root.find("issuer")
    issuer_cik = (_value(issuer, "issuerCik") or "").lstrip("0") or "0"
    issuer_name = _value(issuer, "issuerName") or ""
    ticker = _value(issuer, "issuerTradingSymbol")
    ticker = ticker.strip().upper() if ticker else None
    if ticker in {"", "NONE", "N/A"}:
        ticker = None

    # A Form 4 usually has one reporting owner, but the schema allows several.
    owners = root.findall("reportingOwner")
    if not owners:
        return []
    # Roles: take the union across reporting owners for this filing.
    owner_names: list[str] = []
    is_officer = is_director = is_ten_pct = False
    for owner in owners:
        oid = owner.find("reportingOwnerId")
        name = _value(oid, "rptOwnerName") or _text(
            oid.find("rptOwnerName") if oid is not None else None
        )
        if name:
            owner_names.append(name.strip())
        rel = owner.find("reportingOwnerRelationship")
        if rel is not None:
            is_officer = is_officer or _as_bool(_text(rel.find("isOfficer")))
            is_director = is_director or _as_bool(_text(rel.find("isDirector")))
            is_ten_pct = is_ten_pct or _as_bool(_text(rel.find("isTenPercentOwner")))
    owner_name = "; ".join(owner_names) if owner_names else "UNKNOWN"

    if filed_at is None:
        period = _value(root, "periodOfReport")
        filed_at = _to_dt(period) or datetime.now(UTC)

    buys: list[InsiderBuy] = []
    table = root.find("nonDerivativeTable")
    if table is None:
        return []

    for txn in table.findall("nonDerivativeTransaction"):
        coding = txn.find("transactionCoding")
        code = _text(coding.find("transactionCode")) if coding is not None else None
        if code != BUY_CODE:
            continue  # Ignore S/A/M/G/F/C and anything else.

        amounts = txn.find("transactionAmounts")
        shares = _to_float(_value(amounts, "transactionShares"))
        price = _to_float(_value(amounts, "transactionPricePerShare"))
        if not shares or shares <= 0:
            continue
        if price is None or price <= 0:
            # A "purchase" with no price is not a market buy we can value; skip.
            _log.debug("form4_skip_zero_price", accession_no=accession_no, issuer=issuer_name)
            continue

        txn_date = _to_date(_value(txn, "transactionDate")) or filed_at.date()

        buys.append(
            InsiderBuy(
                accession_no=accession_no,
                issuer_cik=issuer_cik,
                issuer_name=issuer_name,
                ticker=ticker,
                owner_name=owner_name,
                owner_is_officer=is_officer,
                owner_is_director=is_director,
                owner_is_ten_pct=is_ten_pct,
                transaction_date=txn_date,
                shares=shares,
                price_per_share=price,
                filed_at=filed_at,
            )
        )
    return buys


def _to_float(val: str | None) -> float | None:
    if val is None:
        return None
    try:
        return float(val.replace(",", ""))
    except (ValueError, AttributeError):
        return None


def _to_date(val: str | None) -> date | None:
    if not val:
        return None
    try:
        return datetime.strptime(val[:10], "%Y-%m-%d").date()
    except ValueError:
        return None


def _to_dt(val: str | None) -> datetime | None:
    d = _to_date(val)
    return datetime(d.year, d.month, d.day, tzinfo=UTC) if d else None


def fetch_p_buys_for_day(
    day: date,
    client: EdgarClient,
    max_filings: int | None = None,
) -> list[InsiderBuy]:
    """Fetch and parse all Form 4 ``P`` buys filed on ``day``.

    Network-bound: one request for the daily index plus one per Form 4. The
    client rate-limits everything under the SEC ceiling. Returns a flat list of
    every open-market purchase found across all filings.
    """
    index_url = daily_index_url(day)
    _log.info("fetch_daily_index", day=str(day), url=index_url)
    try:
        index_text = client.get_text(index_url)
    except Exception as exc:  # noqa: BLE001 — surface but keep the caller alive.
        _log.error("daily_index_fetch_failed", day=str(day), error=str(exc))
        raise

    refs = parse_daily_index(index_text)
    if max_filings is not None:
        refs = refs[:max_filings]
    _log.info("daily_index_parsed", day=str(day), form4_count=len(refs))

    all_buys: list[InsiderBuy] = []
    for ref in refs:
        try:
            txt = client.get_text(ref.txt_url)
        except Exception as exc:  # noqa: BLE001
            _log.warning("form4_fetch_failed", accession_no=ref.accession_no, error=str(exc))
            continue
        xml = extract_ownership_xml(txt)
        if not xml:
            _log.debug("form4_no_ownership_xml", accession_no=ref.accession_no)
            continue
        filed_at = datetime(
            ref.date_filed.year, ref.date_filed.month, ref.date_filed.day, tzinfo=UTC
        )
        buys = parse_form4_xml(xml, ref.accession_no, filed_at)
        if buys:
            all_buys.extend(buys)
    _log.info("p_buys_extracted", day=str(day), count=len(all_buys))
    return all_buys
