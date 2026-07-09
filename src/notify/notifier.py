"""Structured logging setup + notification sink.

Every meaningful event goes through structured logs. Notable events (fills,
exits, guard trips, exceptions) additionally fan out to a notification sink —
Slack if ``SLACK_WEBHOOK_URL`` is set, otherwise log-only.

Design principle from the spec: *fail loud*. Notifications are best-effort and
must never raise into the caller, but a failed notification is itself logged.
"""

from __future__ import annotations

import logging
import sys
from typing import Any

import httpx
import structlog

from config.settings import get_settings

_CONFIGURED = False


def configure_logging(level: str | None = None) -> None:
    """Configure structlog to emit JSON lines to stdout. Idempotent."""
    global _CONFIGURED
    if _CONFIGURED:
        return

    settings = get_settings()
    log_level = (level or settings.log_level).upper()
    numeric_level = getattr(logging, log_level, logging.INFO)

    logging.basicConfig(
        format="%(message)s",
        stream=sys.stdout,
        level=numeric_level,
    )

    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            structlog.processors.add_log_level,
            structlog.processors.TimeStamper(fmt="iso", utc=True),
            structlog.processors.StackInfoRenderer(),
            structlog.processors.format_exc_info,
            structlog.processors.JSONRenderer(),
        ],
        wrapper_class=structlog.make_filtering_bound_logger(numeric_level),
        logger_factory=structlog.PrintLoggerFactory(),
        cache_logger_on_first_use=True,
    )
    _CONFIGURED = True


def get_logger(name: str = "trader") -> structlog.stdlib.BoundLogger:
    """Return a bound structured logger, configuring logging on first use."""
    configure_logging()
    return structlog.get_logger(name)


_LEVEL_TO_INT = {
    "debug": logging.DEBUG,
    "info": logging.INFO,
    "warning": logging.WARNING,
    "error": logging.ERROR,
    "critical": logging.CRITICAL,
}


def notify(event: str, level: str = "info", slack: bool = False, **fields: Any) -> None:
    """Log a structured event and, for notable levels, push to Slack.

    ``level`` is one of debug/info/warning/error/critical. Anything at warning
    or above is sent to the Slack sink (if configured); pass ``slack=True`` to
    force a push at info level too (used for startup + daily heartbeat). This
    function never raises — a failed notification is logged and swallowed so it
    can't take down a trading job.
    """
    log = get_logger()
    lvl = level.lower()
    log_method = getattr(log, lvl, log.info)
    log_method(event, **fields)

    if slack or _LEVEL_TO_INT.get(lvl, logging.INFO) >= logging.WARNING:
        _send_slack(event, lvl, fields)


def notify_fill(ticker: str, side: str, notional: float, order_id: str, **fields: Any) -> None:
    """Convenience wrapper: fills are always pushed to the notification sink."""
    log = get_logger()
    log.info(
        "order_filled", ticker=ticker, side=side, notional=notional, order_id=order_id, **fields
    )
    _send_slack(
        "order_filled",
        "info",
        {"ticker": ticker, "side": side, "notional": notional, "order_id": order_id, **fields},
        force=True,
    )


def _send_slack(event: str, level: str, fields: dict[str, Any], force: bool = False) -> None:
    settings = get_settings()
    url = settings.slack_webhook_url.strip()
    if not url:
        return  # Log-only fallback; already logged by the caller.

    emoji = {
        "info": ":information_source:",
        "warning": ":warning:",
        "error": ":rotating_light:",
    }.get(level, ":information_source:")
    detail = " ".join(f"`{k}={v}`" for k, v in fields.items())
    text = f"{emoji} *{event}* {detail}".strip()

    try:
        resp = httpx.post(url, json={"text": text}, timeout=5.0)
        resp.raise_for_status()
    except Exception as exc:  # noqa: BLE001 — best-effort sink, must not raise.
        # Fail loud in the logs, but never propagate into a trading job.
        get_logger().warning("slack_notify_failed", error=str(exc), original_event=event)
