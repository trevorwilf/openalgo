"""v5 Phase 3 — venue-local datetime helpers (region-neutral).

Complements ``database.venue_offset`` (which returns the UTC offset
in seconds for a venue/date pair). The helpers here render
``datetime`` values in a venue's local time using the venue's IANA
timezone, never hard-coding ``Asia/Kolkata`` / ``IST``.

India venues remain bit-identical (the venue tz lookup returns
``Asia/Kolkata`` for the India venue codes); non-India venues honor
DST via ``zoneinfo``.

This module is region-neutral PROMOTED_CORE. Callers that want to
display a wall-clock time for a venue (e.g., "session ends at 16:00
ET", "scheduler job fires at 09:30 ET") should use
``venue_local_now(venue_code)`` and ``format_venue_local_time(...)``
rather than constructing their own ``zoneinfo`` calls.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

try:
    from zoneinfo import ZoneInfo
except ImportError:  # pragma: no cover
    ZoneInfo = None  # type: ignore

from utils.logging import get_logger

logger = get_logger(__name__)

# India venue codes — short-circuit to Asia/Kolkata (parity with the
# database.venue_offset shim).
_INDIA_VENUE_CODES = frozenset(
    {"NSE", "BSE", "NFO", "BFO", "CDS", "BCD", "MCX", "NSE_INDEX", "BSE_INDEX"}
)
_INDIA_TZ_NAME = "Asia/Kolkata"

# Mirror the venue→tz table in database.venue_offset so this helper
# stays import-light (utils/* must not import database.instruments_repo
# per the no-coupling contract). Add new MIC codes here when region
# plugins seed them.
_VENUE_TZ_NAME: dict[str, str] = {
    "XNYS": "America/New_York",
    "XNAS": "America/New_York",
    "ARCX": "America/New_York",
    "BATS": "America/New_York",
    "IEXG": "America/New_York",
    "XPAR": "Europe/Paris",
    "XAMS": "Europe/Amsterdam",
    "XBRU": "Europe/Brussels",
    "XETR": "Europe/Berlin",
    "XLON": "Europe/London",
    "XHKG": "Asia/Hong_Kong",
    "XSES": "Asia/Singapore",
    "XTKS": "Asia/Tokyo",
    "XASX": "Australia/Sydney",
}


def _venue_iana_tz(venue_code: str) -> Optional[str]:
    """Return the IANA timezone name for a venue code, or None.

    Resolution:
      * India venue codes (NSE/BSE/...) → Asia/Kolkata.
      * Known non-India MIC codes → mapped IANA name from the table
        above.
      * Anything else → None.
    """
    code = (venue_code or "").strip().upper()
    if not code:
        return None
    if code in _INDIA_VENUE_CODES:
        return _INDIA_TZ_NAME
    return _VENUE_TZ_NAME.get(code)


def venue_local_now(venue_code: str) -> Optional[datetime]:
    """Return the current wall-clock time in the given venue's tz.

    Returns ``None`` when the venue tz cannot be resolved. Callers that
    need fail-closed behavior should branch on the None.
    """
    tz_name = _venue_iana_tz(venue_code)
    if not tz_name:
        return None
    if ZoneInfo is None:
        return None
    try:
        return datetime.now(ZoneInfo(tz_name))
    except Exception as e:  # pragma: no cover - defensive
        logger.debug("venue_local_now(%r) failed: %s", venue_code, e)
        return None


def to_venue_local(when_utc: datetime, venue_code: str) -> Optional[datetime]:
    """Convert a UTC datetime to the venue's local tz.

    ``when_utc`` must be timezone-aware; naive datetimes return None
    (do not silently assume UTC — that's how silent-fallback bugs are
    born).
    """
    if when_utc.tzinfo is None:
        logger.debug("to_venue_local: naive datetime rejected")
        return None
    tz_name = _venue_iana_tz(venue_code)
    if not tz_name or ZoneInfo is None:
        return None
    try:
        return when_utc.astimezone(ZoneInfo(tz_name))
    except Exception as e:  # pragma: no cover
        logger.debug("to_venue_local(%r) failed: %s", venue_code, e)
        return None


def format_venue_local_time(
    when: datetime,
    venue_code: str,
    *,
    fmt: str = "%Y-%m-%d %H:%M:%S %Z",
) -> Optional[str]:
    """Render a UTC-aware datetime as a venue-local string with the
    short tz name appended (e.g., 'IST', 'EST', 'EDT', 'CET')."""
    local = to_venue_local(when, venue_code)
    if local is None:
        return None
    return local.strftime(fmt)


def active_render_tz_name() -> str:
    """Return the IANA tz name for the active region's primary venue.

    Render-side helper used by operator-facing blueprints (P&L tracker,
    analyzer, health, latency, log, traffic). India operators see
    ``Asia/Kolkata`` (bit-identical legacy behavior); non-India
    operators see their region's primary venue tz.

    Resolution chain (mirrors
    :func:`services.feature_gate_service.active_region_code`):

    1. Active broker session's region (via active_region_code) →
       region plugin's first ``default_venue_codes`` entry → its
       IANA tz via :func:`_venue_iana_tz`.
    2. When the region resolves but the venue lookup fails (e.g.,
       region declares no default venues), falls back to the region
       plugin's ``timezone_name``.
    3. When no region resolves (no broker, no settings, no env
       override), returns ``"Asia/Kolkata"`` so legacy India
       deployments keep wall-clock display unchanged.

    The render layer never raises — a failed lookup falls through
    to ``Asia/Kolkata`` rather than crashing a user-facing view.
    Fail-closed behavior belongs in write paths (cf. T-10/T-11
    SESSION_EXPIRY_TIMEZONE / DOWNLOAD_VENUE_TZ) where a wrong
    answer corrupts data.
    """
    try:
        from services.feature_gate_service import active_region_code

        region = active_region_code()
    except Exception:
        return _INDIA_TZ_NAME

    try:
        from services.market_region_service import get_market_region
        from utils.region_loader import load_market_regions

        plugin = get_market_region(region)
        if plugin is None:
            # Region cache is empty — typical in test contexts where
            # the Flask app's startup hook hasn't run. Load once and
            # retry. In production the app's bootstrap path triggers
            # this so the second call is a no-op for hot paths.
            load_market_regions()
            plugin = get_market_region(region)
    except Exception:
        plugin = None

    if plugin is not None:
        for venue_code in getattr(plugin, "default_venue_codes", []) or []:
            tz_name = _venue_iana_tz(venue_code)
            if tz_name:
                return tz_name
        # Region resolved but no venue tz — fall back to the region's
        # declared timezone_name.
        tz_name = getattr(plugin, "timezone_name", None)
        if tz_name:
            return tz_name

    return _INDIA_TZ_NAME


__all__ = [
    "active_render_tz_name",
    "format_venue_local_time",
    "to_venue_local",
    "venue_local_now",
]
