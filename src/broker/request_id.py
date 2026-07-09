"""Capture Alpaca's ``X-Request-ID`` response header for support/debugging.

Every Alpaca Trading API response carries a unique ``X-Request-ID`` header that
identifies the call in Alpaca's systems. Alpaca explicitly recommends persisting
recent Request IDs so they can be quoted in support tickets — they can't be
queried after the fact from any other endpoint.

alpaca-py talks to the API through a ``requests.Session``. We attach a response
hook to that session so *every* call — account, orders, positions, clock —
records its Request ID with zero changes to the SDK call sites. The most recent
IDs are kept in a small thread-safe ring buffer and logged structured (the JSON
logs are themselves the durable record), and the latest is surfaced on failures.
"""

from __future__ import annotations

import threading
from collections import deque
from typing import Any

REQUEST_ID_HEADER = "X-Request-ID"


class RequestIdTracker:
    """Thread-safe ring buffer of the most recent Alpaca Request IDs."""

    def __init__(self, maxlen: int = 50) -> None:
        self._ids: deque[tuple[str, str]] = deque(maxlen=maxlen)
        self._lock = threading.Lock()

    def record(self, request_id: str, path: str) -> None:
        with self._lock:
            self._ids.append((request_id, path))

    @property
    def last(self) -> str | None:
        """The most recent Request ID seen, or None if no call has been made."""
        with self._lock:
            return self._ids[-1][0] if self._ids else None

    def recent(self, n: int = 10) -> list[tuple[str, str]]:
        """Return up to the last ``n`` (request_id, path) pairs, newest last."""
        with self._lock:
            return list(self._ids)[-n:]


def attach_request_id_capture(session: Any, tracker: RequestIdTracker, log: Any) -> None:
    """Register a ``requests`` response hook that records every Request ID.

    ``session`` is the ``requests.Session`` used by alpaca-py's REST client
    (``client._session``). The hook is best-effort: it must never raise into the
    SDK's request path, so any failure to read the header is swallowed.
    """

    def _hook(response: Any, *args: Any, **kwargs: Any) -> Any:
        try:
            request_id = response.headers.get(REQUEST_ID_HEADER)
            if request_id:
                path = getattr(response.request, "path_url", "") or getattr(response, "url", "")
                tracker.record(request_id, path)
                # Debug level: high-volume, but the durable audit trail lives here.
                log.debug(
                    "alpaca_request_id",
                    request_id=request_id,
                    path=path,
                    status=response.status_code,
                )
        except Exception:  # noqa: BLE001 — capture must never break a request.
            pass
        return response

    hooks = session.hooks.setdefault("response", [])
    if isinstance(hooks, list):
        hooks.append(_hook)
    else:  # requests allows a single callable; normalize to a list.
        session.hooks["response"] = [hooks, _hook]
