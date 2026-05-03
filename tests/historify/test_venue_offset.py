"""Phase 7 v4 (ADR 0023) — database.venue_offset.venue_local_offset_seconds.

Confirms India venues return 19800 year-round (parity-protected) and
non-India venues compute a DST-correct UTC offset from their IANA
timezone.
"""

from __future__ import annotations

from datetime import date

import pytest

from database.venue_offset import venue_local_offset_seconds


@pytest.mark.parametrize("venue", ["NSE", "BSE", "NFO", "BFO", "CDS", "MCX"])
def test_india_venues_always_return_19800(venue):
    for d in (date(2026, 1, 15), date(2026, 4, 15), date(2026, 7, 15), date(2026, 10, 15)):
        assert venue_local_offset_seconds(venue, d) == 19800, (
            f"{venue} on {d}: expected 19800 (Asia/Kolkata DST-free)"
        )


def test_none_venue_is_fail_closed():
    """Phase 1 T-07 — venue_local_offset_seconds(None) raises
    VenueResolutionError. The prior implicit Asia/Kolkata fallback for
    a missing venue code was removed so callers must pass an explicit
    venue.
    """
    from domain.errors import VenueResolutionError

    with pytest.raises(VenueResolutionError):
        venue_local_offset_seconds(None)


def test_unknown_venue_falls_back_to_india_default():
    """Unknown but explicit venue code still returns the India default
    (19800). Per the implementation docstring this is the last
    remaining implicit-India fallback inside the helper, retained
    because ``database.historify_db`` SQL bucketing requires a numeric
    offset. A future region-plugin-driven venue catalog will replace
    this lookup (see ADR 0023).
    """
    assert venue_local_offset_seconds("UNKNOWN_VENUE") == 19800


def test_xnys_summer_uses_dst_offset():
    """In summer XNYS is EDT = UTC-4 = -14400 seconds."""
    assert venue_local_offset_seconds("XNYS", date(2026, 7, 15)) == -14400


def test_xnys_winter_uses_standard_offset():
    """In winter XNYS is EST = UTC-5 = -18000 seconds."""
    assert venue_local_offset_seconds("XNYS", date(2026, 1, 15)) == -18000


def test_xnas_matches_xnys():
    assert venue_local_offset_seconds("XNAS", date(2026, 7, 15)) == -14400
    assert venue_local_offset_seconds("XNAS", date(2026, 1, 15)) == -18000


def test_xpar_summer_uses_cest():
    """Europe/Paris in summer is CEST = UTC+2 = 7200 seconds."""
    assert venue_local_offset_seconds("XPAR", date(2026, 7, 15)) == 7200


def test_xpar_winter_uses_cet():
    """Europe/Paris in winter is CET = UTC+1 = 3600 seconds."""
    assert venue_local_offset_seconds("XPAR", date(2026, 1, 15)) == 3600


def test_xlon_summer_uses_bst():
    """Europe/London in summer is BST = UTC+1 = 3600 seconds."""
    assert venue_local_offset_seconds("XLON", date(2026, 7, 15)) == 3600


def test_xlon_winter_uses_gmt():
    """Europe/London in winter is GMT = UTC+0 = 0 seconds."""
    assert venue_local_offset_seconds("XLON", date(2026, 1, 15)) == 0


def test_case_insensitive_venue_lookup():
    assert venue_local_offset_seconds("xnys", date(2026, 7, 15)) == -14400
    assert venue_local_offset_seconds("nse") == 19800
