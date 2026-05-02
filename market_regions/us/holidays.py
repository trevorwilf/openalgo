"""US market holidays — Phase 7b T-30 build-out.

NYSE / NASDAQ trading holidays for calendar years 2024 through 2027.
Source documents: NYSE official holiday calendars and SEC press
releases. The list is intentionally a Python data table (no runtime
dependency on ``pandas-market-calendars``) so this module is a
deterministic source of truth for the US sandbox + parity tests.

Schema (mirrors :mod:`market_regions.india.holidays`)::

    {
        "date": "YYYY-MM-DD",
        "description": str,
        "holiday_type": "TRADING_HOLIDAY" | "EARLY_CLOSE",
        "closed": list[str],            # venue codes fully closed
        "open": list[dict],             # special-session windows
                                        # (used for early-close days
                                        # to record the 13:00 ET stop)
    }

Early-close days (typically the day after Thanksgiving and Christmas
Eve when on a weekday) record an EARLY_CLOSE entry whose ``open[]``
holds a single 09:30-13:00 ET window for each equity venue.
"""

from __future__ import annotations

from typing import Any


_EQUITY_VENUES: tuple[str, ...] = ("XNYS", "XNAS", "ARCX", "BATS")


def _equity_closed() -> list[str]:
    return list(_EQUITY_VENUES)


def _early_close_windows() -> list[dict[str, Any]]:
    """09:30 - 13:00 ET window for each equity venue. Times are
    encoded as the venue's local-time string here; the calendar
    seeder converts to UTC at load time."""
    return [
        {"exchange": v, "local_start_time": "09:30", "local_end_time": "13:00"}
        for v in _EQUITY_VENUES
    ]


HOLIDAYS_2024: list[dict[str, Any]] = [
    {"date": "2024-01-01", "description": "New Year's Day",
     "holiday_type": "TRADING_HOLIDAY", "closed": _equity_closed(), "open": []},
    {"date": "2024-01-15", "description": "Martin Luther King Jr. Day",
     "holiday_type": "TRADING_HOLIDAY", "closed": _equity_closed(), "open": []},
    {"date": "2024-02-19", "description": "Presidents' Day",
     "holiday_type": "TRADING_HOLIDAY", "closed": _equity_closed(), "open": []},
    {"date": "2024-03-29", "description": "Good Friday",
     "holiday_type": "TRADING_HOLIDAY", "closed": _equity_closed(), "open": []},
    {"date": "2024-05-27", "description": "Memorial Day",
     "holiday_type": "TRADING_HOLIDAY", "closed": _equity_closed(), "open": []},
    {"date": "2024-06-19", "description": "Juneteenth National Independence Day",
     "holiday_type": "TRADING_HOLIDAY", "closed": _equity_closed(), "open": []},
    {"date": "2024-07-03", "description": "Independence Day (Eve, early close)",
     "holiday_type": "EARLY_CLOSE", "closed": [], "open": _early_close_windows()},
    {"date": "2024-07-04", "description": "Independence Day",
     "holiday_type": "TRADING_HOLIDAY", "closed": _equity_closed(), "open": []},
    {"date": "2024-09-02", "description": "Labor Day",
     "holiday_type": "TRADING_HOLIDAY", "closed": _equity_closed(), "open": []},
    {"date": "2024-11-28", "description": "Thanksgiving Day",
     "holiday_type": "TRADING_HOLIDAY", "closed": _equity_closed(), "open": []},
    {"date": "2024-11-29", "description": "Day after Thanksgiving (early close)",
     "holiday_type": "EARLY_CLOSE", "closed": [], "open": _early_close_windows()},
    {"date": "2024-12-24", "description": "Christmas Eve (early close)",
     "holiday_type": "EARLY_CLOSE", "closed": [], "open": _early_close_windows()},
    {"date": "2024-12-25", "description": "Christmas Day",
     "holiday_type": "TRADING_HOLIDAY", "closed": _equity_closed(), "open": []},
]


HOLIDAYS_2025: list[dict[str, Any]] = [
    {"date": "2025-01-01", "description": "New Year's Day",
     "holiday_type": "TRADING_HOLIDAY", "closed": _equity_closed(), "open": []},
    {"date": "2025-01-09", "description": "Day of Mourning - Jimmy Carter",
     "holiday_type": "TRADING_HOLIDAY", "closed": _equity_closed(), "open": []},
    {"date": "2025-01-20", "description": "Martin Luther King Jr. Day",
     "holiday_type": "TRADING_HOLIDAY", "closed": _equity_closed(), "open": []},
    {"date": "2025-02-17", "description": "Presidents' Day",
     "holiday_type": "TRADING_HOLIDAY", "closed": _equity_closed(), "open": []},
    {"date": "2025-04-18", "description": "Good Friday",
     "holiday_type": "TRADING_HOLIDAY", "closed": _equity_closed(), "open": []},
    {"date": "2025-05-26", "description": "Memorial Day",
     "holiday_type": "TRADING_HOLIDAY", "closed": _equity_closed(), "open": []},
    {"date": "2025-06-19", "description": "Juneteenth National Independence Day",
     "holiday_type": "TRADING_HOLIDAY", "closed": _equity_closed(), "open": []},
    {"date": "2025-07-03", "description": "Independence Day (Eve, early close)",
     "holiday_type": "EARLY_CLOSE", "closed": [], "open": _early_close_windows()},
    {"date": "2025-07-04", "description": "Independence Day",
     "holiday_type": "TRADING_HOLIDAY", "closed": _equity_closed(), "open": []},
    {"date": "2025-09-01", "description": "Labor Day",
     "holiday_type": "TRADING_HOLIDAY", "closed": _equity_closed(), "open": []},
    {"date": "2025-11-27", "description": "Thanksgiving Day",
     "holiday_type": "TRADING_HOLIDAY", "closed": _equity_closed(), "open": []},
    {"date": "2025-11-28", "description": "Day after Thanksgiving (early close)",
     "holiday_type": "EARLY_CLOSE", "closed": [], "open": _early_close_windows()},
    {"date": "2025-12-24", "description": "Christmas Eve (early close)",
     "holiday_type": "EARLY_CLOSE", "closed": [], "open": _early_close_windows()},
    {"date": "2025-12-25", "description": "Christmas Day",
     "holiday_type": "TRADING_HOLIDAY", "closed": _equity_closed(), "open": []},
]


HOLIDAYS_2026: list[dict[str, Any]] = [
    {"date": "2026-01-01", "description": "New Year's Day",
     "holiday_type": "TRADING_HOLIDAY", "closed": _equity_closed(), "open": []},
    {"date": "2026-01-19", "description": "Martin Luther King Jr. Day",
     "holiday_type": "TRADING_HOLIDAY", "closed": _equity_closed(), "open": []},
    {"date": "2026-02-16", "description": "Presidents' Day",
     "holiday_type": "TRADING_HOLIDAY", "closed": _equity_closed(), "open": []},
    {"date": "2026-04-03", "description": "Good Friday",
     "holiday_type": "TRADING_HOLIDAY", "closed": _equity_closed(), "open": []},
    {"date": "2026-05-25", "description": "Memorial Day",
     "holiday_type": "TRADING_HOLIDAY", "closed": _equity_closed(), "open": []},
    {"date": "2026-06-19", "description": "Juneteenth National Independence Day",
     "holiday_type": "TRADING_HOLIDAY", "closed": _equity_closed(), "open": []},
    {"date": "2026-07-03", "description": "Independence Day (observed)",
     "holiday_type": "TRADING_HOLIDAY", "closed": _equity_closed(), "open": []},
    {"date": "2026-09-07", "description": "Labor Day",
     "holiday_type": "TRADING_HOLIDAY", "closed": _equity_closed(), "open": []},
    {"date": "2026-11-26", "description": "Thanksgiving Day",
     "holiday_type": "TRADING_HOLIDAY", "closed": _equity_closed(), "open": []},
    {"date": "2026-11-27", "description": "Day after Thanksgiving (early close)",
     "holiday_type": "EARLY_CLOSE", "closed": [], "open": _early_close_windows()},
    {"date": "2026-12-24", "description": "Christmas Eve (early close)",
     "holiday_type": "EARLY_CLOSE", "closed": [], "open": _early_close_windows()},
    {"date": "2026-12-25", "description": "Christmas Day",
     "holiday_type": "TRADING_HOLIDAY", "closed": _equity_closed(), "open": []},
]


HOLIDAYS_2027: list[dict[str, Any]] = [
    {"date": "2027-01-01", "description": "New Year's Day",
     "holiday_type": "TRADING_HOLIDAY", "closed": _equity_closed(), "open": []},
    {"date": "2027-01-18", "description": "Martin Luther King Jr. Day",
     "holiday_type": "TRADING_HOLIDAY", "closed": _equity_closed(), "open": []},
    {"date": "2027-02-15", "description": "Presidents' Day",
     "holiday_type": "TRADING_HOLIDAY", "closed": _equity_closed(), "open": []},
    {"date": "2027-03-26", "description": "Good Friday",
     "holiday_type": "TRADING_HOLIDAY", "closed": _equity_closed(), "open": []},
    {"date": "2027-05-31", "description": "Memorial Day",
     "holiday_type": "TRADING_HOLIDAY", "closed": _equity_closed(), "open": []},
    {"date": "2027-06-18", "description": "Juneteenth (observed)",
     "holiday_type": "TRADING_HOLIDAY", "closed": _equity_closed(), "open": []},
    {"date": "2027-07-05", "description": "Independence Day (observed)",
     "holiday_type": "TRADING_HOLIDAY", "closed": _equity_closed(), "open": []},
    {"date": "2027-09-06", "description": "Labor Day",
     "holiday_type": "TRADING_HOLIDAY", "closed": _equity_closed(), "open": []},
    {"date": "2027-11-25", "description": "Thanksgiving Day",
     "holiday_type": "TRADING_HOLIDAY", "closed": _equity_closed(), "open": []},
    {"date": "2027-11-26", "description": "Day after Thanksgiving (early close)",
     "holiday_type": "EARLY_CLOSE", "closed": [], "open": _early_close_windows()},
    {"date": "2027-12-24", "description": "Christmas Eve (early close)",
     "holiday_type": "EARLY_CLOSE", "closed": [], "open": _early_close_windows()},
]


HOLIDAYS_BY_YEAR: dict[int, list[dict[str, Any]]] = {
    2024: HOLIDAYS_2024,
    2025: HOLIDAYS_2025,
    2026: HOLIDAYS_2026,
    2027: HOLIDAYS_2027,
}


__all__ = [
    "HOLIDAYS_2024",
    "HOLIDAYS_2025",
    "HOLIDAYS_2026",
    "HOLIDAYS_2027",
    "HOLIDAYS_BY_YEAR",
]
