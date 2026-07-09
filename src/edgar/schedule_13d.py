"""Optional Schedule 13D ingestion (built last, intentionally minimal).

Schedule 13D filings signal that an activist/large holder has crossed 5%
ownership with intent to influence — a different, slower signal than a Form 4
open-market buy. It is NOT wired into the trading path; it exists as a scaffold
for a future secondary signal source. The primary and only trading signal today
is Form 4 code ``P`` buys.

To keep the honest-about-limits promise: 13D parsing here is a stub that lists
13D/13D-A filings from the daily index. It does not yet extract ownership
percentages or intent, and nothing consumes its output.
"""

from __future__ import annotations

from datetime import date

from src.edgar.client import EdgarClient
from src.edgar.form4 import FilingRef, daily_index_url, parse_daily_index
from src.notify.notifier import get_logger

_log = get_logger("schedule_13d")


def list_13d_filings(day: date, client: EdgarClient) -> list[FilingRef]:
    """Return 13D / 13D/A filing references from the daily index for a date.

    Provided for future use; not part of the trading loop. Extracting ownership
    percentage and stated intent from the 13D body is left as future work.
    """
    index_text = client.get_text(daily_index_url(day))
    refs = parse_daily_index(index_text, form_types=("SC 13D", "SC 13D/A"))
    _log.info("schedule_13d_listed", day=str(day), count=len(refs))
    return refs
