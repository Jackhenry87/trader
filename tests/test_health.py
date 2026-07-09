"""Heartbeat / health-check tests."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from src.health import heartbeat_age_seconds, is_healthy, write_heartbeat


def test_write_and_read_heartbeat_fresh(tmp_path):
    p = str(tmp_path / "hb")
    now = datetime(2026, 1, 1, 12, 0, 0, tzinfo=UTC)
    write_heartbeat(p, now=now)
    age = heartbeat_age_seconds(p, now=now + timedelta(seconds=30))
    assert age == 30
    assert is_healthy(p, max_age_seconds=180, now=now + timedelta(seconds=30)) is True


def test_stale_heartbeat_is_unhealthy(tmp_path):
    p = str(tmp_path / "hb")
    now = datetime(2026, 1, 1, 12, 0, 0, tzinfo=UTC)
    write_heartbeat(p, now=now)
    later = now + timedelta(seconds=300)
    assert heartbeat_age_seconds(p, now=later) == 300
    assert is_healthy(p, max_age_seconds=180, now=later) is False


def test_missing_heartbeat_is_unhealthy(tmp_path):
    p = str(tmp_path / "does_not_exist")
    assert heartbeat_age_seconds(p) is None
    assert is_healthy(p, max_age_seconds=180) is False


def test_unparseable_heartbeat_is_unhealthy(tmp_path):
    p = tmp_path / "hb"
    p.write_text("not-a-timestamp")
    assert heartbeat_age_seconds(str(p)) is None
    assert is_healthy(str(p), max_age_seconds=180) is False


def test_heartbeat_creates_parent_dir(tmp_path):
    p = str(tmp_path / "nested" / "dir" / "hb")
    write_heartbeat(p)
    assert is_healthy(p, max_age_seconds=180) is True
