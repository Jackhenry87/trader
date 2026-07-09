"""Rate-limited SEC EDGAR HTTP client.

The SEC requires a real ``User-Agent`` (``"Name email@domain.com"``) or EDGAR
returns HTTP 403, and asks callers to stay at or below 10 requests/second. This
client enforces both: a token-bucket-ish rate limiter caps request rate, and
every request carries the configured User-Agent. Requests retry with backoff on
transient failures.
"""

from __future__ import annotations

import threading
import time

import httpx
from tenacity import (
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

from config.settings import get_settings
from src.notify.notifier import get_logger

# Stay comfortably under the SEC's 10 req/s ceiling.
MAX_REQUESTS_PER_SECOND = 8.0
_MIN_INTERVAL = 1.0 / MAX_REQUESTS_PER_SECOND


class RateLimiter:
    """Simple thread-safe minimum-interval limiter.

    Guarantees successive acquisitions are spaced at least ``min_interval``
    seconds apart. Not a full token bucket, but sufficient for a single-process
    bot that must never exceed the SEC's rate limit.
    """

    def __init__(self, min_interval: float = _MIN_INTERVAL) -> None:
        self._min_interval = min_interval
        self._lock = threading.Lock()
        self._next_allowed = 0.0

    def acquire(self) -> None:
        with self._lock:
            now = time.monotonic()
            wait = self._next_allowed - now
            if wait > 0:
                time.sleep(wait)
                now = time.monotonic()
            self._next_allowed = now + self._min_interval


class EdgarClient:
    """Thin, rate-limited wrapper over ``httpx`` for sec.gov requests."""

    def __init__(self, user_agent: str | None = None, timeout: float = 20.0) -> None:
        settings = get_settings()
        self._user_agent = user_agent or settings.require_sec_user_agent()
        self._limiter = RateLimiter()
        self._log = get_logger("edgar")
        self._client = httpx.Client(
            timeout=timeout,
            headers={
                "User-Agent": self._user_agent,
                # EDGAR wants these; hostnames must match the resource being hit.
                "Accept-Encoding": "gzip, deflate",
                "Host": "www.sec.gov",
            },
            follow_redirects=True,
        )

    @retry(
        retry=retry_if_exception_type((httpx.TransportError, httpx.HTTPStatusError)),
        stop=stop_after_attempt(4),
        wait=wait_exponential(multiplier=1, min=1, max=16),
        reraise=True,
    )
    def get(self, url: str) -> httpx.Response:
        """GET a sec.gov URL, rate-limited and retried with backoff.

        Retries on transport errors and 5xx/429. 403/404 are surfaced
        immediately (retrying a 403 just wastes the rate budget).
        """
        self._limiter.acquire()
        # The Host header must match the URL's host, so let httpx set it.
        headers = {"User-Agent": self._user_agent}
        resp = self._client.get(url, headers=headers)
        if resp.status_code in (429,) or resp.status_code >= 500:
            self._log.warning("edgar_retryable_status", url=url, status=resp.status_code)
            resp.raise_for_status()
        if resp.status_code >= 400:
            # Non-retryable client error (403/404 etc). Fail loud.
            self._log.error("edgar_client_error", url=url, status=resp.status_code)
            resp.raise_for_status()
        return resp

    def get_text(self, url: str) -> str:
        return self.get(url).text

    def get_bytes(self, url: str) -> bytes:
        return self.get(url).content

    def close(self) -> None:
        self._client.close()

    def __enter__(self) -> EdgarClient:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()
