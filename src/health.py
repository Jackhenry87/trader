"""Liveness heartbeat for the scheduler + a health check for Docker.

The scheduler writes a heartbeat timestamp every minute. Two things consume it:

* ``docker`` HEALTHCHECK runs ``python -m src.main health``, which exits non-zero
  when the heartbeat is missing or stale — so a wedged scheduler is marked
  unhealthy and restarted by the ``restart: unless-stopped`` policy.
* A daily Slack "still alive" ping acts as a dead-man's switch: if you stop
  seeing it, the bot is down.

Kept dependency-free and pure where possible so it is trivially testable.
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path


def write_heartbeat(path: str, now: datetime | None = None) -> None:
    """Write the current UTC timestamp to the heartbeat file."""
    now = now or datetime.now(UTC)
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(now.isoformat())


def heartbeat_age_seconds(path: str, now: datetime | None = None) -> float | None:
    """Age of the heartbeat in seconds, or None if missing/unparseable."""
    now = now or datetime.now(UTC)
    p = Path(path)
    if not p.exists():
        return None
    try:
        ts = datetime.fromisoformat(p.read_text().strip())
    except (ValueError, OSError):
        return None
    if ts.tzinfo is None:
        ts = ts.replace(tzinfo=UTC)
    return (now - ts).total_seconds()


def is_healthy(path: str, max_age_seconds: float, now: datetime | None = None) -> bool:
    """True when a fresh heartbeat exists within ``max_age_seconds``."""
    age = heartbeat_age_seconds(path, now)
    return age is not None and age <= max_age_seconds
