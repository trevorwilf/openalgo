"""Phase 7 v4 (ADR 0023) — venue-aware UTC offset helper.

Replaces the hardcoded ``ist_offset = 19800`` in
``database.historify_db`` aggregation queries with a venue-aware
lookup. India venues (NSE/BSE/NFO/BFO/CDS/MCX) return 19800
year-round (Asia/Kolkata is DST-free); other venues compute their
offset via :mod:`zoneinfo` for the supplied date.

The function is intentionally small and side-effect-free so it can
be imported into the SQL-string templating without a database round
trip.
"""

from __future__ import annotations

from datetime import date, datetime
from zoneinfo import ZoneInfo

# India venues are DST-free at +5:30. Hardcoding 19800 preserves the
# legacy SQL byte-identically when the resolved venue is India.
_INDIA_VENUES: frozenset[str] = frozenset({
    "NSE", "BSE", "NFO", "BFO", "CDS", "MCX", "NSE_INDEX", "BSE_INDEX", "BCD",
})

_INDIA_OFFSET_SECONDS = 19800

# Map known non-India venue codes to their IANA timezone. Add new
# venues here as the region plugins seed them. The fallback for an
# unknown venue is ``Asia/Kolkata`` (legacy India behavior preserved).
_VENUE_TZ: dict[str, str] = {
    "XNYS": "America/New_York",
    "XNAS": "America/New_York",
    "ARCX": "America/New_York",
    "BATS": "America/New_York",
    "IEXG": "America/New_York",
    "XPAR": "Europe/Paris",
    "XETR": "Europe/Berlin",
    "XLON": "Europe/London",
}


def venue_local_offset_seconds(
    venue_code: str | None = None,
    on_date: date | None = None,
) -> int:
    """Return the UTC offset (seconds) for ``venue_code`` on ``on_date``.

    Behavior:
        * ``None`` or unknown venue → ``19800`` (Asia/Kolkata legacy
          default; preserves bit-identical India aggregation behavior).
        * India venue (NSE / BSE / NFO / BFO / CDS / MCX / NSE_INDEX / BSE_INDEX / BCD)
          → ``19800`` (Asia/Kolkata is DST-free).
        * Known non-India venue → computed from its IANA timezone for
          ``on_date`` (defaults to today). Returns the standard or
          DST offset as appropriate.
    """
    if venue_code is None:
        return _INDIA_OFFSET_SECONDS
    code = str(venue_code).strip().upper()
    if code in _INDIA_VENUES:
        return _INDIA_OFFSET_SECONDS
    tz_name = _VENUE_TZ.get(code)
    if tz_name is None:
        return _INDIA_OFFSET_SECONDS
    asof = on_date or date.today()
    tz = ZoneInfo(tz_name)
    dt = datetime(asof.year, asof.month, asof.day, 12, 0).replace(tzinfo=tz)
    offset = dt.utcoffset()
    if offset is None:
        return _INDIA_OFFSET_SECONDS
    return int(offset.total_seconds())


__all__ = ["venue_local_offset_seconds"]
