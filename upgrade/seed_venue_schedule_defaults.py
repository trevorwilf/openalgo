#!/usr/bin/env python3
"""Seed venue rows + schedule templates for Phase 4.

Covered venues
--------------
India (delivery-today brokers):
    NSE, BSE, NFO, BFO, CDS, BCD, MCX, NCDEX, NSE_INDEX, BSE_INDEX
Crypto:
    CRYPTO, DELTA_EXCHANGE
Design-target reference seeds (NOT authoritative for production):
    NYSE, NASDAQ, LSE, XETRA, EURONEXT_PAR, SIX

** These templates are best-effort REFERENCE DATA **

They are NOT authoritative for production trading scheduling. Production
operators must cross-check against each venue's public schedule before
using. Sources below for the non-Indian venues (as of 2024):

    NYSE / NASDAQ: https://www.nyse.com/markets/hours-calendars
    LSE:           https://www.londonstockexchange.com/trade-on-our-markets
    XETRA:         https://www.deutsche-boerse-cash-market.com/
    EURONEXT PAR:  https://live.euronext.com/en/resources/trading-hours
    SIX:           https://www.six-group.com/ (SIX Swiss Exchange trading hours)

The seed is idempotent — rows are upserted on ``(venue_code,
day_of_week, session_type)``.

Usage::

    cd upgrade
    uv run seed_venue_schedule_defaults.py
"""

from __future__ import annotations

import os
import sys
from datetime import time
from typing import Any

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dotenv import load_dotenv  # noqa: E402

env_path = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), ".env"
)
load_dotenv(env_path)

from utils.logging import get_logger  # noqa: E402

logger = get_logger(__name__)


# ---------------------------------------------------------------------------
# Seed data
# ---------------------------------------------------------------------------

# day_of_week: 0=Mon .. 4=Fri, 5=Sat, 6=Sun, -1=every day (crypto).
WEEKDAYS = (0, 1, 2, 3, 4)
ALL_DAYS = (0, 1, 2, 3, 4, 5, 6)


# (venue_code, market_family, timezone_name, country_code, base_currency,
#  session_model, display_name, [(day_tuple, session_type, start, end), ...])
VENUE_SEEDS: list[dict[str, Any]] = [
    # ---- India cash/equity ------------------------------------------------
    {
        "venue_code": "NSE",
        "market_family": "IN_STOCK",
        "timezone_name": "Asia/Kolkata",
        "country_code": "IN",
        "base_currency": "INR",
        "session_model": "continuous",
        "display_name": "National Stock Exchange of India",
        "templates": [
            (WEEKDAYS, "REGULAR", time(9, 15), time(15, 30)),
        ],
    },
    {
        "venue_code": "BSE",
        "market_family": "IN_STOCK",
        "timezone_name": "Asia/Kolkata",
        "country_code": "IN",
        "base_currency": "INR",
        "session_model": "continuous",
        "display_name": "Bombay Stock Exchange",
        "templates": [
            (WEEKDAYS, "REGULAR", time(9, 15), time(15, 30)),
        ],
    },
    {
        "venue_code": "NFO",
        "market_family": "IN_STOCK",
        "timezone_name": "Asia/Kolkata",
        "country_code": "IN",
        "base_currency": "INR",
        "session_model": "continuous",
        "display_name": "NSE Futures & Options",
        "templates": [
            (WEEKDAYS, "REGULAR", time(9, 15), time(15, 30)),
        ],
    },
    {
        "venue_code": "BFO",
        "market_family": "IN_STOCK",
        "timezone_name": "Asia/Kolkata",
        "country_code": "IN",
        "base_currency": "INR",
        "session_model": "continuous",
        "display_name": "BSE Futures & Options",
        "templates": [
            (WEEKDAYS, "REGULAR", time(9, 15), time(15, 30)),
        ],
    },
    {
        "venue_code": "CDS",
        "market_family": "IN_STOCK",
        "timezone_name": "Asia/Kolkata",
        "country_code": "IN",
        "base_currency": "INR",
        "session_model": "continuous",
        "display_name": "NSE Currency Derivatives",
        "templates": [
            (WEEKDAYS, "REGULAR", time(9, 0), time(17, 0)),
        ],
    },
    {
        "venue_code": "BCD",
        "market_family": "IN_STOCK",
        "timezone_name": "Asia/Kolkata",
        "country_code": "IN",
        "base_currency": "INR",
        "session_model": "continuous",
        "display_name": "BSE Currency Derivatives",
        "templates": [
            (WEEKDAYS, "REGULAR", time(9, 0), time(17, 0)),
        ],
    },
    {
        "venue_code": "MCX",
        "market_family": "IN_STOCK",
        "timezone_name": "Asia/Kolkata",
        "country_code": "IN",
        "base_currency": "INR",
        "session_model": "continuous",
        "display_name": "Multi Commodity Exchange",
        "templates": [
            (WEEKDAYS, "REGULAR", time(9, 0), time(23, 55)),
        ],
    },
    {
        "venue_code": "NCDEX",
        "market_family": "IN_STOCK",
        "timezone_name": "Asia/Kolkata",
        "country_code": "IN",
        "base_currency": "INR",
        "session_model": "continuous",
        "display_name": "National Commodity & Derivatives Exchange",
        "templates": [
            (WEEKDAYS, "REGULAR", time(9, 0), time(21, 0)),
        ],
    },
    {
        "venue_code": "NSE_INDEX",
        "market_family": "IN_STOCK",
        "timezone_name": "Asia/Kolkata",
        "country_code": "IN",
        "base_currency": "INR",
        "session_model": "continuous",
        "display_name": "NSE Indices",
        "templates": [
            (WEEKDAYS, "REGULAR", time(9, 15), time(15, 30)),
        ],
    },
    {
        "venue_code": "BSE_INDEX",
        "market_family": "IN_STOCK",
        "timezone_name": "Asia/Kolkata",
        "country_code": "IN",
        "base_currency": "INR",
        "session_model": "continuous",
        "display_name": "BSE Indices",
        "templates": [
            (WEEKDAYS, "REGULAR", time(9, 15), time(15, 30)),
        ],
    },
    # ---- Crypto -----------------------------------------------------------
    {
        "venue_code": "CRYPTO",
        "market_family": "CRYPTO",
        "timezone_name": "UTC",
        "country_code": None,
        "base_currency": "USDT",
        "session_model": "twenty_four_seven",
        "display_name": "Crypto (generic)",
        "templates": [
            # day_of_week = -1 (every day), session type ALL_DAY.
            ((-1,), "ALL_DAY", time(0, 0), time(23, 59, 59)),
        ],
    },
    {
        "venue_code": "DELTA_EXCHANGE",
        "market_family": "CRYPTO",
        "timezone_name": "UTC",
        "country_code": None,
        "base_currency": "USDT",
        "session_model": "twenty_four_seven",
        "display_name": "Delta Exchange (crypto derivatives)",
        "templates": [
            ((-1,), "ALL_DAY", time(0, 0), time(23, 59, 59)),
        ],
    },
    # ---- US equities (reference; post-Phase-6 adapter target) -------------
    {
        "venue_code": "XNYS",
        "market_family": "US_STOCK",
        "timezone_name": "America/New_York",
        "country_code": "US",
        "base_currency": "USD",
        "session_model": "continuous",
        "display_name": "New York Stock Exchange",
        "templates": [
            (WEEKDAYS, "PRE_MARKET", time(4, 0), time(9, 30)),
            (WEEKDAYS, "REGULAR", time(9, 30), time(16, 0)),
            (WEEKDAYS, "POST_MARKET", time(16, 0), time(20, 0)),
        ],
    },
    {
        "venue_code": "XNAS",
        "market_family": "US_STOCK",
        "timezone_name": "America/New_York",
        "country_code": "US",
        "base_currency": "USD",
        "session_model": "continuous",
        "display_name": "NASDAQ",
        "templates": [
            (WEEKDAYS, "PRE_MARKET", time(4, 0), time(9, 30)),
            (WEEKDAYS, "REGULAR", time(9, 30), time(16, 0)),
            (WEEKDAYS, "POST_MARKET", time(16, 0), time(20, 0)),
        ],
    },
    # ---- European equities (reference) ------------------------------------
    {
        "venue_code": "XLON",
        "market_family": "UK_STOCK",
        "timezone_name": "Europe/London",
        "country_code": "GB",
        "base_currency": "GBP",
        "session_model": "continuous_with_auctions",
        "display_name": "London Stock Exchange",
        "templates": [
            (WEEKDAYS, "OPENING_AUCTION", time(7, 50), time(8, 0)),
            (WEEKDAYS, "REGULAR", time(8, 0), time(16, 30)),
            (WEEKDAYS, "CLOSING_AUCTION", time(16, 30), time(16, 35)),
        ],
    },
    {
        "venue_code": "XETR",
        "market_family": "EU_STOCK",
        "timezone_name": "Europe/Berlin",
        "country_code": "DE",
        "base_currency": "EUR",
        "session_model": "continuous_with_auctions",
        "display_name": "Deutsche Börse Xetra",
        "templates": [
            (WEEKDAYS, "OPENING_AUCTION", time(8, 50), time(9, 0)),
            (WEEKDAYS, "REGULAR", time(9, 0), time(17, 30)),
            (WEEKDAYS, "CLOSING_AUCTION", time(17, 30), time(17, 35)),
        ],
    },
    {
        "venue_code": "XPAR",
        "market_family": "EU_STOCK",
        "timezone_name": "Europe/Paris",
        "country_code": "FR",
        "base_currency": "EUR",
        "session_model": "continuous_with_auctions",
        "display_name": "Euronext Paris",
        "templates": [
            (WEEKDAYS, "OPENING_AUCTION", time(8, 50), time(9, 0)),
            (WEEKDAYS, "REGULAR", time(9, 0), time(17, 30)),
            (WEEKDAYS, "CLOSING_AUCTION", time(17, 30), time(17, 35)),
        ],
    },
    {
        "venue_code": "XSWX",
        "market_family": "EU_STOCK",
        "timezone_name": "Europe/Zurich",
        "country_code": "CH",
        "base_currency": "CHF",
        "session_model": "continuous_with_auctions",
        "display_name": "SIX Swiss Exchange",
        "templates": [
            (WEEKDAYS, "OPENING_AUCTION", time(8, 50), time(9, 0)),
            (WEEKDAYS, "REGULAR", time(9, 0), time(17, 20)),
            (WEEKDAYS, "CLOSING_AUCTION", time(17, 20), time(17, 30)),
        ],
    },
]


def seed_all() -> dict[str, int]:
    from database.venue_schedule_repo import (
        init_venue_schedule_tables,
        upsert_schedule_template,
    )
    from database.instruments_repo import venues_upsert

    init_venue_schedule_tables()

    venue_count = 0
    template_count = 0

    for v in VENUE_SEEDS:
        venues_upsert(
            v["venue_code"],
            market_family=v["market_family"],
            timezone_name=v["timezone_name"],
            country_code=v["country_code"],
            base_currency=v["base_currency"],
            session_model=v["session_model"],
            display_name=v["display_name"],
        )
        venue_count += 1
        for day_tuple, session_type, start, end in v["templates"]:
            for day in day_tuple:
                upsert_schedule_template(
                    venue_code=v["venue_code"],
                    day_of_week=day,
                    session_type=session_type,
                    starts_at_local=start,
                    ends_at_local=end,
                )
                template_count += 1

    logger.info(
        "Seeded %d venues with %d schedule templates", venue_count, template_count
    )
    return {"venues": venue_count, "templates": template_count}


def main() -> int:
    logger.info("=" * 60)
    logger.info("OpenAlgo — Phase 4 venue schedule seed")
    logger.info("=" * 60)
    stats = seed_all()
    logger.info("Seeded: %s", stats)
    return 0


if __name__ == "__main__":
    sys.exit(main())
