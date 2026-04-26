"""Phase 3 v4 (ADR 0023) — DST coverage for promoted venues.

For each non-India venue declared in the region plugins, the venue's
declared timezone must produce the correct UTC offset across the
spring-forward and fall-back boundaries for the next two years. This
locks the contract that session conversions remain DST-correct
without any India-specific assumptions.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

import pytest

# (venue_code, tz_name, spring_forward_dates, fall_back_dates)
# Spring-forward dates are the first day on which the local clock
# moves +1h; fall-back dates the day on which it moves -1h. We sample
# 2026 and 2027 explicitly so the test ages well.
PROMOTED_VENUE_DST_CASES = [
    ("XNYS", "America/New_York",
     [date(2026, 3, 8), date(2027, 3, 14)],
     [date(2026, 11, 1), date(2027, 11, 7)]),
    ("XNAS", "America/New_York",
     [date(2026, 3, 8), date(2027, 3, 14)],
     [date(2026, 11, 1), date(2027, 11, 7)]),
    ("ARCX", "America/New_York",
     [date(2026, 3, 8), date(2027, 3, 14)],
     [date(2026, 11, 1), date(2027, 11, 7)]),
    ("XPAR", "Europe/Paris",
     [date(2026, 3, 29), date(2027, 3, 28)],
     [date(2026, 10, 25), date(2027, 10, 31)]),
    ("XETR", "Europe/Berlin",
     [date(2026, 3, 29), date(2027, 3, 28)],
     [date(2026, 10, 25), date(2027, 10, 31)]),
    ("XLON", "Europe/London",
     [date(2026, 3, 29), date(2027, 3, 28)],
     [date(2026, 10, 25), date(2027, 10, 31)]),
]


def _utc_offset_hours(tz_name: str, on_date: date, hour: int = 12) -> float:
    tz = ZoneInfo(tz_name)
    dt = datetime(on_date.year, on_date.month, on_date.day, hour, 0).replace(tzinfo=tz)
    offset = dt.utcoffset()
    assert offset is not None
    return offset.total_seconds() / 3600


@pytest.mark.parametrize("venue_code,tz_name,spring_dates,fall_dates", PROMOTED_VENUE_DST_CASES)
def test_promoted_venue_dst_offsets_change_across_boundaries(
    venue_code, tz_name, spring_dates, fall_dates
):
    for d in spring_dates:
        # Day before spring forward — standard time. Day after — DST.
        before = _utc_offset_hours(tz_name, d - timedelta(days=1))
        after = _utc_offset_hours(tz_name, d + timedelta(days=1))
        assert after > before, (
            f"{venue_code} ({tz_name}): expected spring-forward to increase "
            f"UTC offset on {d}; got {before} -> {after}"
        )
    for d in fall_dates:
        before = _utc_offset_hours(tz_name, d - timedelta(days=1))
        after = _utc_offset_hours(tz_name, d + timedelta(days=1))
        assert after < before, (
            f"{venue_code} ({tz_name}): expected fall-back to decrease "
            f"UTC offset on {d}; got {before} -> {after}"
        )


def test_india_venues_are_dst_free():
    """Asia/Kolkata is DST-free year-round at +5:30."""
    tz = ZoneInfo("Asia/Kolkata")
    for month in (1, 4, 7, 10):
        dt = datetime(2026, month, 15, 12, 0).replace(tzinfo=tz)
        offset_hours = dt.utcoffset().total_seconds() / 3600
        assert offset_hours == 5.5, f"India tz drifted in month {month}: {offset_hours}"
