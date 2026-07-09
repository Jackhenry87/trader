"""Parser tests: only code-P non-derivative buys are extracted."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from src.edgar.form4 import extract_ownership_xml, parse_daily_index, parse_form4_xml

FIXTURE = Path(__file__).parent / "fixtures" / "sample_form4.xml"


def _sample_xml() -> str:
    return FIXTURE.read_text()


def test_extracts_only_p_transactions():
    buys = parse_form4_xml(_sample_xml(), accession_no="0000320193-24-000001")
    # Two P buys in the non-derivative table; S, A (grant), and derivative M ignored.
    assert len(buys) == 2
    assert all(b.ticker == "ACME" for b in buys)


def test_ignores_sales_grants_and_option_exercises():
    buys = parse_form4_xml(_sample_xml(), accession_no="acc-1")
    # No sale (S), grant (A), or option exercise (M) should appear.
    shares = sorted(b.shares for b in buys)
    assert shares == [500.0, 1000.0]  # only the two P rows


def test_extracts_issuer_owner_and_roles():
    buys = parse_form4_xml(_sample_xml(), accession_no="acc-1")
    b = buys[0]
    assert b.issuer_name == "ACME WIDGETS INC"
    assert b.issuer_cik == "320193"  # leading zeros stripped
    assert b.owner_is_officer is True
    assert b.owner_is_director is True
    assert b.owner_is_ten_pct is False
    assert "officer" in b.owner_relationship and "director" in b.owner_relationship


def test_value_usd_computed():
    buys = parse_form4_xml(_sample_xml(), accession_no="acc-1")
    values = sorted(b.value_usd for b in buys)
    # 500 * 26.00 = 13,000 ; 1000 * 25.50 = 25,500
    assert values == [13000.0, 25500.0]


def test_zero_price_purchase_skipped():
    xml = """<ownershipDocument>
      <issuer><issuerCik>1</issuerCik><issuerName>Z</issuerName>
        <issuerTradingSymbol>Z</issuerTradingSymbol></issuer>
      <reportingOwner><reportingOwnerId><rptOwnerName>X</rptOwnerName></reportingOwnerId>
        <reportingOwnerRelationship><isOfficer>1</isOfficer></reportingOwnerRelationship>
      </reportingOwner>
      <nonDerivativeTable><nonDerivativeTransaction>
        <transactionCoding><transactionCode>P</transactionCode></transactionCoding>
        <transactionAmounts>
          <transactionShares><value>100</value></transactionShares>
          <transactionPricePerShare><value>0</value></transactionPricePerShare>
        </transactionAmounts>
      </nonDerivativeTransaction></nonDerivativeTable>
    </ownershipDocument>"""
    assert parse_form4_xml(xml, "acc-zero") == []


def test_missing_ticker_still_parses_buy():
    xml = """<ownershipDocument>
      <issuer><issuerCik>42</issuerCik><issuerName>NoTicker Co</issuerName>
        <issuerTradingSymbol></issuerTradingSymbol></issuer>
      <reportingOwner><reportingOwnerId><rptOwnerName>Y</rptOwnerName></reportingOwnerId>
        <reportingOwnerRelationship><isTenPercentOwner>1</isTenPercentOwner></reportingOwnerRelationship>
      </reportingOwner>
      <nonDerivativeTable><nonDerivativeTransaction>
        <transactionDate><value>2024-01-02</value></transactionDate>
        <transactionCoding><transactionCode>P</transactionCode></transactionCoding>
        <transactionAmounts>
          <transactionShares><value>10</value></transactionShares>
          <transactionPricePerShare><value>5</value></transactionPricePerShare>
        </transactionAmounts>
      </nonDerivativeTransaction></nonDerivativeTable>
    </ownershipDocument>"""
    buys = parse_form4_xml(xml, "acc-nt")
    assert len(buys) == 1
    assert buys[0].ticker is None
    assert buys[0].owner_is_ten_pct is True


def test_extract_ownership_xml_from_submission():
    submission = (
        "SEC-HEADER stuff\n<DOCUMENT>\n<TYPE>4\n<XML>\n"
        + _sample_xml()
        + "\n</XML>\n</DOCUMENT>\ntrailer"
    )
    xml = extract_ownership_xml(submission)
    assert xml is not None
    buys = parse_form4_xml(xml, "acc-embed")
    assert len(buys) == 2


def test_filed_at_used_when_provided():
    filed = datetime(2024, 5, 11, tzinfo=UTC)
    buys = parse_form4_xml(_sample_xml(), "acc-1", filed_at=filed)
    assert all(b.filed_at == filed for b in buys)


DAILY_INDEX_SAMPLE = """Description:           Daily Index of EDGAR Dissemination Feed by Form Type
Last Data Received:    May 10, 2024
Comment:               ...

Form Type   Company Name                                              CIK         Date Filed  File Name
---------------------------------------------------------------------------------------------------------
4           ACME WIDGETS INC                                          320193      2024-05-10  edgar/data/320193/0000320193-24-000001.txt
4/A         BETA CORP                                                 111111      2024-05-10  edgar/data/111111/0001111111-24-000002.txt
8-K         GAMMA LLC                                                 222222      2024-05-10  edgar/data/222222/0002222222-24-000003.txt
"""


def test_daily_index_parses_form4_rows_only():
    refs = parse_daily_index(DAILY_INDEX_SAMPLE)
    assert len(refs) == 2  # the 4 and 4/A, not the 8-K
    r0 = refs[0]
    assert r0.form_type == "4"
    assert r0.company_name == "ACME WIDGETS INC"
    assert r0.cik == "320193"
    assert r0.accession_no == "0000320193-24-000001"
    assert r0.txt_url.endswith("edgar/data/320193/0000320193-24-000001.txt")
