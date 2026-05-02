"""India market holiday calendar — Phase 2 T-09 relocation.

Source of truth for India trading holidays and special sessions.
Relocated byte-equivalently from
``database/market_calendar_db.py:307-470`` so the seed function in
``database/market_calendar_db.py`` reads from here without changing
a single byte of holiday data.

Schema for each entry::

    {
        "date": "YYYY-MM-DD",
        "description": str,
        "holiday_type": "TRADING_HOLIDAY" | "SPECIAL_SESSION",
        "closed": list[str],            # exchange codes fully closed
        "open": list[dict],             # special-session windows
    }

``open[i]`` carries epoch-millisecond ``start_time`` / ``end_time``
in IST. The Muhurat-trading window is part of the SPECIAL_SESSION
type. Source documents: NSE Circular & MCX Circular for Calendar
Year 2026.
"""

from __future__ import annotations

from typing import Any


HOLIDAYS_2026: list[dict[str, Any]] = [
    # January
    {
        "date": "2026-01-15",
        "description": "Municipal Corporation Election - Maharashtra",
        "holiday_type": "TRADING_HOLIDAY",
        "closed": ["NSE", "BSE", "NFO", "BFO", "CDS", "BCD"],
        "open": [
            {"exchange": "MCX", "start_time": 1768476600000, "end_time": 1768501500000}
        ],  # MCX evening 17:00-23:55
    },
    {
        "date": "2026-01-26",
        "description": "Republic Day",
        "holiday_type": "TRADING_HOLIDAY",
        "closed": ["NSE", "BSE", "NFO", "BFO", "CDS", "BCD", "MCX"],
        "open": [],
    },
    # March
    {
        "date": "2026-03-03",
        "description": "Holi",
        "holiday_type": "TRADING_HOLIDAY",
        "closed": ["NSE", "BSE", "NFO", "BFO", "CDS", "BCD"],
        "open": [
            {"exchange": "MCX", "start_time": 1772537400000, "end_time": 1772562300000}
        ],  # MCX evening 17:00-23:55
    },
    {
        "date": "2026-03-26",
        "description": "Shri Ram Navami",
        "holiday_type": "TRADING_HOLIDAY",
        "closed": ["NSE", "BSE", "NFO", "BFO", "CDS", "BCD"],
        "open": [
            {"exchange": "MCX", "start_time": 1774524600000, "end_time": 1774549500000}
        ],  # MCX evening 17:00-23:55
    },
    {
        "date": "2026-03-31",
        "description": "Shri Mahavir Jayanti",
        "holiday_type": "TRADING_HOLIDAY",
        "closed": ["NSE", "BSE", "NFO", "BFO", "CDS", "BCD"],
        "open": [
            {"exchange": "MCX", "start_time": 1774956600000, "end_time": 1774981500000}
        ],  # MCX evening 17:00-23:55
    },
    # April
    {
        "date": "2026-04-03",
        "description": "Good Friday",
        "holiday_type": "TRADING_HOLIDAY",
        "closed": ["NSE", "BSE", "NFO", "BFO", "CDS", "BCD", "MCX"],
        "open": [],
    },
    {
        "date": "2026-04-14",
        "description": "Dr. Baba Saheb Ambedkar Jayanti",
        "holiday_type": "TRADING_HOLIDAY",
        "closed": ["NSE", "BSE", "NFO", "BFO", "CDS", "BCD"],
        "open": [
            {"exchange": "MCX", "start_time": 1776166200000, "end_time": 1776191100000}
        ],  # MCX evening 17:00-23:55
    },
    # May
    {
        "date": "2026-05-01",
        "description": "Maharashtra Day",
        "holiday_type": "TRADING_HOLIDAY",
        "closed": ["NSE", "BSE", "NFO", "BFO", "CDS", "BCD"],
        "open": [
            {"exchange": "MCX", "start_time": 1777635000000, "end_time": 1777659900000}
        ],  # MCX evening 17:00-23:55
    },
    {
        "date": "2026-05-28",
        "description": "Bakri Id",
        "holiday_type": "TRADING_HOLIDAY",
        "closed": ["NSE", "BSE", "NFO", "BFO", "CDS", "BCD"],
        "open": [
            {"exchange": "MCX", "start_time": 1779967800000, "end_time": 1779992700000}
        ],  # MCX evening 17:00-23:55
    },
    # June
    {
        "date": "2026-06-26",
        "description": "Muharram",
        "holiday_type": "TRADING_HOLIDAY",
        "closed": ["NSE", "BSE", "NFO", "BFO", "CDS", "BCD"],
        "open": [
            {"exchange": "MCX", "start_time": 1782473400000, "end_time": 1782498300000}
        ],  # MCX evening 17:00-23:55
    },
    # September
    {
        "date": "2026-09-14",
        "description": "Ganesh Chaturthi",
        "holiday_type": "TRADING_HOLIDAY",
        "closed": ["NSE", "BSE", "NFO", "BFO", "CDS", "BCD"],
        "open": [
            {"exchange": "MCX", "start_time": 1789385400000, "end_time": 1789410300000}
        ],  # MCX evening 17:00-23:55
    },
    # October
    {
        "date": "2026-10-02",
        "description": "Mahatma Gandhi Jayanti",
        "holiday_type": "TRADING_HOLIDAY",
        "closed": ["NSE", "BSE", "NFO", "BFO", "CDS", "BCD", "MCX"],
        "open": [],
    },
    {
        "date": "2026-10-20",
        "description": "Dussehra",
        "holiday_type": "TRADING_HOLIDAY",
        "closed": ["NSE", "BSE", "NFO", "BFO", "CDS", "BCD"],
        "open": [
            {"exchange": "MCX", "start_time": 1792495800000, "end_time": 1792520700000}
        ],  # MCX evening 17:00-23:55
    },
    # November - Diwali with Muhurat Trading
    {
        "date": "2026-11-08",
        "description": "Diwali Laxmi Pujan (Muhurat Trading)",
        "holiday_type": "SPECIAL_SESSION",
        "closed": [],
        "open": [
            # Muhurat Trading session — default 18:00 to 19:15 IST (exact timings via circular)
            {"exchange": "NSE", "start_time": 1794141000000, "end_time": 1794145500000},
            {"exchange": "BSE", "start_time": 1794141000000, "end_time": 1794145500000},
            {"exchange": "NFO", "start_time": 1794141000000, "end_time": 1794145500000},
            {"exchange": "BFO", "start_time": 1794141000000, "end_time": 1794145500000},
            {"exchange": "CDS", "start_time": 1794141000000, "end_time": 1794145500000},
            {"exchange": "BCD", "start_time": 1794141000000, "end_time": 1794145500000},
            # MCX Muhurat — 18:00 to 00:15 (next day)
            {"exchange": "MCX", "start_time": 1794141000000, "end_time": 1794163500000},
        ],
    },
    {
        "date": "2026-11-10",
        "description": "Diwali Balipratipada",
        "holiday_type": "TRADING_HOLIDAY",
        "closed": ["NSE", "BSE", "NFO", "BFO", "CDS", "BCD"],
        "open": [
            {"exchange": "MCX", "start_time": 1794310200000, "end_time": 1794335100000}
        ],  # MCX evening 17:00-23:55
    },
    {
        "date": "2026-11-24",
        "description": "Prakash Gurpurb Sri Guru Nanak Dev",
        "holiday_type": "TRADING_HOLIDAY",
        "closed": ["NSE", "BSE", "NFO", "BFO", "CDS", "BCD"],
        "open": [
            {"exchange": "MCX", "start_time": 1795519800000, "end_time": 1795544700000}
        ],  # MCX evening 17:00-23:55
    },
    # December
    {
        "date": "2026-12-25",
        "description": "Christmas",
        "holiday_type": "TRADING_HOLIDAY",
        "closed": ["NSE", "BSE", "NFO", "BFO", "CDS", "BCD", "MCX"],
        "open": [],
    },
]


__all__ = ["HOLIDAYS_2026"]
