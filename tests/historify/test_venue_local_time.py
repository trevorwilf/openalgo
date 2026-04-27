"""v5 Phase 3 — venue_local_time helper tests."""

from __future__ import annotations

from datetime import datetime, timezone

from utils.venue_local_time import (
    format_venue_local_time,
    to_venue_local,
    venue_local_now,
)


def test_venue_local_now_india_returns_ist_aware_datetime():
    now = venue_local_now("NSE")
    assert now is not None
    assert now.tzinfo is not None
    # IST is +05:30
    assert now.utcoffset().total_seconds() == 5 * 3600 + 1800


def test_venue_local_now_unknown_venue_returns_none():
    assert venue_local_now("XHKG_NOT_REGISTERED") is None


def test_to_venue_local_rejects_naive_datetime():
    assert to_venue_local(datetime(2026, 4, 15, 12, 0), "NSE") is None


def test_to_venue_local_india_round_trips_offset():
    when_utc = datetime(2026, 4, 15, 6, 0, tzinfo=timezone.utc)
    local = to_venue_local(when_utc, "NSE")
    assert local is not None
    assert local.utcoffset().total_seconds() == 5 * 3600 + 1800
    # 06:00 UTC = 11:30 IST
    assert local.hour == 11
    assert local.minute == 30


def test_format_venue_local_time_india_includes_short_tz():
    when_utc = datetime(2026, 4, 15, 6, 0, tzinfo=timezone.utc)
    formatted = format_venue_local_time(when_utc, "NSE")
    assert formatted is not None
    assert "11:30:00" in formatted
    # Some platforms render IST short name; fall back to "+0530" on others.
    assert ("IST" in formatted) or ("+0530" in formatted)


def test_format_venue_local_time_unknown_returns_none():
    when_utc = datetime(2026, 4, 15, 6, 0, tzinfo=timezone.utc)
    assert format_venue_local_time(when_utc, "XHKG_NOT_REGISTERED") is None
