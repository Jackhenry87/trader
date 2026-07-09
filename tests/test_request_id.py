"""Tests for Alpaca X-Request-ID capture (ring buffer + session hook)."""

from __future__ import annotations

import logging
from types import SimpleNamespace

from src.broker.request_id import (
    REQUEST_ID_HEADER,
    RequestIdTracker,
    attach_request_id_capture,
)


def test_tracker_records_and_returns_last():
    t = RequestIdTracker()
    assert t.last is None
    t.record("id-1", "/v2/account")
    t.record("id-2", "/v2/orders")
    assert t.last == "id-2"
    assert t.recent(1) == [("id-2", "/v2/orders")]


def test_tracker_ring_buffer_bounded():
    t = RequestIdTracker(maxlen=3)
    for i in range(5):
        t.record(f"id-{i}", "/p")
    recent = t.recent(10)
    assert len(recent) == 3
    assert recent[0][0] == "id-2"  # oldest two evicted
    assert t.last == "id-4"


def _fake_response(request_id: str | None):
    headers = {REQUEST_ID_HEADER: request_id} if request_id else {}
    return SimpleNamespace(
        headers=headers,
        request=SimpleNamespace(path_url="/v2/account"),
        url="https://paper-api.alpaca.markets/v2/account",
        status_code=200,
    )


def test_hook_captures_request_id_from_session():
    tracker = RequestIdTracker()
    session = SimpleNamespace(hooks={})
    attach_request_id_capture(session, tracker, logging.getLogger("test"))

    hooks = session.hooks["response"]
    assert callable(hooks[0])
    # Simulate requests firing the hook on a response.
    hooks[0](_fake_response("abc123"))
    assert tracker.last == "abc123"


def test_hook_is_noop_without_header():
    tracker = RequestIdTracker()
    session = SimpleNamespace(hooks={})
    attach_request_id_capture(session, tracker, logging.getLogger("test"))
    session.hooks["response"][0](_fake_response(None))
    assert tracker.last is None


def test_hook_never_raises_on_bad_response():
    tracker = RequestIdTracker()
    session = SimpleNamespace(hooks={})
    attach_request_id_capture(session, tracker, logging.getLogger("test"))
    # A response object missing .headers must not raise into the request path.
    session.hooks["response"][0](object())
    assert tracker.last is None
