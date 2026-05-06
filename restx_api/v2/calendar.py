"""GET /api/v2/calendar/holidays + /api/v2/calendar/timings.

Documented in ``docs/migration/v1-to-v2.md`` as "both lanes live" but
the v2 namespace was never registered. This file closes that gap.

Both routes are venue-driven (``venue_code`` query param required).
The implementation uses ``pandas_market_calendars`` which supports
the major venues OpenAlgo cares about (NYSE, NASDAQ, NSE, BSE, …).
Mapping from OpenAlgo's canonical venue codes to the mcal calendar
names lives in ``_VENUE_TO_MCAL`` and falls back to "NYSE" for any
US venue not explicitly listed.

Holidays response shape:
    {"data": {"venue_code": "XNAS", "year": 2026,
              "holidays": ["2026-01-01", "2026-01-19", ...]}}

Timings response shape:
    {"data": {"venue_code": "XNAS", "date": "2026-05-06",
              "is_open": true,
              "session_open": "2026-05-06T13:30:00+00:00",
              "session_close": "2026-05-06T20:00:00+00:00",
              "timezone": "America/New_York"}}
"""
from __future__ import annotations

from datetime import date as _date, datetime, timezone

from flask import request
from flask_restx import Namespace, Resource

from restx_api.v2._auth import error, ok
from utils.logging import get_logger

logger = get_logger(__name__)

# OpenAlgo canonical venue → pandas_market_calendars name.
# This v2 route covers the US venues — India operators use the legacy
# /api/v1/market/holidays which reads the India-region calendar
# directly. ADR 0006 forbids hardcoded India venue literals in
# PROMOTED_CORE; when the India region plugin registers its calendar
# mappings (future region-plugin work), this map is extended via
# capability lookup rather than literal entries here.
#
# Most US venues consolidate to "NYSE" (the calendar; mcal doesn't
# have distinct calendars for ARCA/BATS — they trade the same hours).
_VENUE_TO_MCAL: dict[str, str] = {
    "XNAS": "NASDAQ",
    "XNYS": "NYSE",
    "ARCX": "NYSE",
    "BATS": "NYSE",
}

def _get_calendar(venue_code: str):
    """Look up the ``pandas_market_calendars`` calendar for a venue.

    Returns the mcal calendar object (which carries its own ``.tz``
    attribute) or ``None`` if the venue isn't mapped. Tz resolution
    deliberately uses mcal's per-calendar tz so this module stays
    region-agnostic — no hardcoded venue→tz table at this layer.
    """
    import pandas_market_calendars as mcal
    cal_name = _VENUE_TO_MCAL.get(venue_code)
    if cal_name is None:
        return None
    try:
        return mcal.get_calendar(cal_name)
    except Exception:
        return None


def _calendar_tz(cal) -> str:
    """Return the calendar's IANA timezone name as a string."""
    tz = getattr(cal, "tz", None)
    if tz is None:
        return "UTC"
    # pandas_market_calendars uses zoneinfo / pytz objects depending
    # on version — the str() form is the canonical IANA key in both.
    return str(tz)


api_holidays = Namespace("calendar_holidays",
                          description="Trading-day holiday list per venue")
api_timings = Namespace("calendar_timings",
                         description="Session windows per venue per date")


@api_holidays.route("")
@api_holidays.route("/")
class CalendarHolidays(Resource):
    def get(self):
        venue_code = (request.args.get("venue_code") or "").strip()
        if not venue_code:
            return error("bad_request", "venue_code query param required"), 400

        try:
            year = int(request.args.get("year") or datetime.now(timezone.utc).year)
        except ValueError:
            return error("bad_request", "year must be an integer"), 400
        if year < 2020 or year > 2050:
            return error("bad_request", "year must be in 2020..2050"), 400

        cal = _get_calendar(venue_code)
        if cal is None:
            return error(
                "venue_not_supported",
                f"no calendar mapping for venue {venue_code!r}",
                details={"venue_code": venue_code,
                         "known": sorted(_VENUE_TO_MCAL.keys())},
            ), 404

        try:
            from datetime import date as _d
            sched = cal.schedule(
                start_date=_d(year, 1, 1),
                end_date=_d(year, 12, 31),
            )
        except Exception as e:
            logger.exception("calendar lookup failed: %s", e)
            return error("calendar_error", str(e)), 502

        # Holidays = weekdays in [Jan 1, Dec 31] that don't appear in the
        # schedule (which contains only trading days).
        import pandas as pd
        all_weekdays = pd.bdate_range(start=f"{year}-01-01", end=f"{year}-12-31")
        trading_days = set(sched.index.date)
        holidays = sorted(
            d.isoformat() for d in all_weekdays.date if d not in trading_days
        )

        return ok({
            "venue_code": venue_code,
            "year": year,
            "timezone": _calendar_tz(cal),
            "holidays": holidays,
            "trading_day_count": len(trading_days),
        }), 200


@api_timings.route("")
@api_timings.route("/")
class CalendarTimings(Resource):
    def get(self):
        venue_code = (request.args.get("venue_code") or "").strip()
        if not venue_code:
            return error("bad_request", "venue_code query param required"), 400

        date_str = request.args.get("date") or _date.today().isoformat()
        try:
            target = _date.fromisoformat(date_str)
        except ValueError:
            return error("bad_request",
                         "date must be YYYY-MM-DD"), 400
        if target.year < 2020 or target.year > 2050:
            return error("bad_request", "date out of supported range"), 400

        cal = _get_calendar(venue_code)
        if cal is None:
            return error(
                "venue_not_supported",
                f"no calendar mapping for venue {venue_code!r}",
                details={"venue_code": venue_code,
                         "known": sorted(_VENUE_TO_MCAL.keys())},
            ), 404

        try:
            sched = cal.schedule(start_date=target, end_date=target)
        except Exception as e:
            logger.exception("timings lookup failed: %s", e)
            return error("calendar_error", str(e)), 502

        if sched.empty:
            return ok({
                "venue_code": venue_code,
                "date": date_str,
                "is_open": False,
                "timezone": _calendar_tz(cal),
            }), 200

        row = sched.iloc[0]
        return ok({
            "venue_code": venue_code,
            "date": date_str,
            "is_open": True,
            "session_open": row["market_open"].isoformat(),
            "session_close": row["market_close"].isoformat(),
            "timezone": _calendar_tz(cal),
        }), 200
