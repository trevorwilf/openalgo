"""Phase 3 v5 — DST correctness for promoted (non-India) venues.

Synthetic fixtures asserting that ``zoneinfo`` returns the correct UTC
offset across spring-forward / fall-back boundaries for the four
promoted venues this refactor supports today:

* ``America/New_York`` (XNYS / XNAS) — DST observed (EST/EDT).
* ``Europe/London`` (XLON) — DST observed (GMT/BST).
* ``Europe/Paris`` (XPAR / XAMS / XBRU) — DST observed (CET/CEST).
* ``Asia/Kolkata`` (XNSE) — DST never observed (control case).

The test matters because v4 Phase 7 introduced
``database/venue_offset.py::venue_local_offset_seconds`` which delegates
to ``zoneinfo``; this contract test pins the platform's DST contract so
a future Python / tzdata regression that silently breaks DST for any of
these venues fails the gate.
"""

from __future__ import annotations

from datetime import date, datetime, time, timedelta, timezone

import pytest

try:
    from zoneinfo import ZoneInfo
except ImportError:  # pragma: no cover - py < 3.9
    ZoneInfo = None  # type: ignore


def _offset_seconds(tz_name: str, on: date) -> int:
    """Return UTC offset in seconds at noon local on the given date."""
    assert ZoneInfo is not None, "zoneinfo unavailable"
    tz = ZoneInfo(tz_name)
    local = datetime.combine(on, time(12, 0)).replace(tzinfo=tz)
    delta = local.utcoffset()
    assert delta is not None
    return int(delta.total_seconds())


# --- America/New_York ---------------------------------------------------


def test_ny_winter_is_est_minus5h():
    """January is EST (UTC−5)."""
    assert _offset_seconds("America/New_York", date(2026, 1, 15)) == -5 * 3600


def test_ny_summer_is_edt_minus4h():
    """July is EDT (UTC−4)."""
    assert _offset_seconds("America/New_York", date(2026, 7, 15)) == -4 * 3600


def test_ny_dst_starts_second_sunday_of_march():
    """2026 spring-forward: 2026-03-08 02:00 → 03:00 EDT."""
    # On 2026-03-07 noon, still EST.
    assert _offset_seconds("America/New_York", date(2026, 3, 7)) == -5 * 3600
    # On 2026-03-08 noon, EDT (DST started overnight).
    assert _offset_seconds("America/New_York", date(2026, 3, 8)) == -4 * 3600


def test_ny_dst_ends_first_sunday_of_november():
    """2026 fall-back: 2026-11-01 02:00 → 01:00 EST."""
    assert _offset_seconds("America/New_York", date(2026, 10, 31)) == -4 * 3600
    assert _offset_seconds("America/New_York", date(2026, 11, 1)) == -5 * 3600


# --- Europe/London ------------------------------------------------------


def test_london_winter_is_gmt():
    assert _offset_seconds("Europe/London", date(2026, 1, 15)) == 0


def test_london_summer_is_bst_plus1h():
    assert _offset_seconds("Europe/London", date(2026, 7, 15)) == 3600


def test_london_dst_starts_last_sunday_of_march():
    """2026: 2026-03-29 01:00 GMT → 02:00 BST."""
    assert _offset_seconds("Europe/London", date(2026, 3, 28)) == 0
    assert _offset_seconds("Europe/London", date(2026, 3, 29)) == 3600


def test_london_dst_ends_last_sunday_of_october():
    """2026: 2026-10-25 02:00 BST → 01:00 GMT."""
    assert _offset_seconds("Europe/London", date(2026, 10, 24)) == 3600
    assert _offset_seconds("Europe/London", date(2026, 10, 25)) == 0


# --- Europe/Paris (and other CET/CEST venues) ---------------------------


def test_paris_winter_is_cet_plus1h():
    assert _offset_seconds("Europe/Paris", date(2026, 1, 15)) == 3600


def test_paris_summer_is_cest_plus2h():
    assert _offset_seconds("Europe/Paris", date(2026, 7, 15)) == 2 * 3600


def test_paris_dst_starts_last_sunday_of_march():
    """2026: 2026-03-29 02:00 CET → 03:00 CEST."""
    assert _offset_seconds("Europe/Paris", date(2026, 3, 28)) == 3600
    assert _offset_seconds("Europe/Paris", date(2026, 3, 29)) == 2 * 3600


def test_paris_dst_ends_last_sunday_of_october():
    """2026: 2026-10-25 03:00 CEST → 02:00 CET."""
    assert _offset_seconds("Europe/Paris", date(2026, 10, 24)) == 2 * 3600
    assert _offset_seconds("Europe/Paris", date(2026, 10, 25)) == 3600


# --- Asia/Kolkata (control: never observes DST) -------------------------


def test_kolkata_january_is_ist_plus_5h30m():
    assert _offset_seconds("Asia/Kolkata", date(2026, 1, 15)) == 5 * 3600 + 1800


def test_kolkata_july_is_ist_plus_5h30m():
    """India does not observe DST."""
    assert _offset_seconds("Asia/Kolkata", date(2026, 7, 15)) == 5 * 3600 + 1800


def test_kolkata_offset_constant_across_dst_boundary_dates():
    """India's offset never changes across NY's DST transition dates."""
    assert _offset_seconds("Asia/Kolkata", date(2026, 3, 7)) == 5 * 3600 + 1800
    assert _offset_seconds("Asia/Kolkata", date(2026, 3, 8)) == 5 * 3600 + 1800
    assert _offset_seconds("Asia/Kolkata", date(2026, 11, 1)) == 5 * 3600 + 1800


# --- Cross-check: venue_offset shim agrees ------------------------------


def test_venue_offset_shim_agrees_on_dst_transitions():
    """database.venue_offset.venue_local_offset_seconds delegates to
    zoneinfo for non-India venues; it must return the same number as
    the direct ZoneInfo lookup."""
    from database.venue_offset import venue_local_offset_seconds

    cases = [
        ("XNYS", "America/New_York", date(2026, 3, 7), -5 * 3600),
        ("XNYS", "America/New_York", date(2026, 3, 8), -4 * 3600),
        ("XNYS", "America/New_York", date(2026, 11, 1), -5 * 3600),
        ("XLON", "Europe/London", date(2026, 3, 29), 3600),
        ("XLON", "Europe/London", date(2026, 10, 25), 0),
        ("XPAR", "Europe/Paris", date(2026, 3, 29), 2 * 3600),
    ]
    for venue, _tz, on, expected in cases:
        actual = venue_local_offset_seconds(venue, on)
        assert actual == expected, (
            f"venue_local_offset_seconds({venue!r}, {on}) = {actual}, expected {expected}"
        )
