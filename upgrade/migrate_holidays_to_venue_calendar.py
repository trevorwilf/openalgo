#!/usr/bin/env python3
"""Phase 4 — migrate legacy market_holidays into venue_calendar_exceptions.

The legacy ``market_holidays`` + ``market_holiday_exchanges`` tables
hold India calendar data (NSE/BSE/NFO/BFO/CDS/MCX). The Phase 4
``venue_calendar_exceptions`` table is empty for this data.

This script copies every (date, exchange) pair from the legacy
tables into ``venue_calendar_exceptions``. The migration is:

* **Additive** — legacy rows are NEVER deleted. Legacy code
  (`database/market_calendar_db.py`) continues to read from
  `market_holidays` for the legacy lane.
* **Idempotent** — a re-run leaves matching
  ``(venue_code, session_date, exception_type, session_type)`` rows
  unchanged thanks to ``upsert_calendar_exception``.
* **Source-tagged** — every migrated row has
  ``description = "<legacy holiday name>"`` and the metadata
  ``{"source": "legacy_market_holidays_migration", "legacy_holiday_id": <id>}``.

Run from project root::

    uv run python upgrade/migrate_holidays_to_venue_calendar.py

Optional flags::

    --dry-run    Report what would happen without writing.
"""

from __future__ import annotations

import argparse
import os
import sys
from datetime import time as dt_time
from typing import Iterable

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dotenv import load_dotenv  # noqa: E402

env_path = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), ".env"
)
load_dotenv(env_path)

from utils.logging import get_logger  # noqa: E402

logger = get_logger(__name__)


def _legacy_rows() -> Iterable[tuple]:
    """Yield (holiday_id, holiday_date, description, holiday_type,
    exchange_code, is_open, start_time_ms, end_time_ms) tuples joined
    across ``market_holidays`` and ``market_holiday_exchanges``."""
    from database.market_calendar_db import (
        Holiday,
        HolidayExchange,
        db_session,
    )

    rows = (
        db_session.query(
            Holiday.id,
            Holiday.holiday_date,
            Holiday.description,
            Holiday.holiday_type,
            HolidayExchange.exchange_code,
            HolidayExchange.is_open,
            HolidayExchange.start_time,
            HolidayExchange.end_time,
        )
        .join(HolidayExchange, HolidayExchange.holiday_id == Holiday.id)
        .all()
    )
    yield from rows


def _ms_offset_to_local_time(ms: int | None) -> dt_time | None:
    """Convert a milliseconds-from-midnight offset to a `datetime.time`.

    Legacy `market_holiday_exchanges.{start_time,end_time}` store
    epoch-millis values in IST. The math reduces them to a wall-clock
    HH:MM:SS in IST (which is what the venue tz already is for Indian
    venues, so the conversion is identity).
    """
    if ms is None:
        return None
    seconds = (ms // 1000) % 86400
    h, rem = divmod(seconds, 3600)
    m, s = divmod(rem, 60)
    return dt_time(h, m, s)


def _legacy_to_exception_args(row) -> dict:
    """Map a legacy joined row to keyword args for
    ``venue_schedule_repo.upsert_calendar_exception``.
    """
    holiday_id, holiday_date, description, holiday_type, exchange_code, \
        is_open, start_ms, end_ms = row

    if holiday_type == "SPECIAL_SESSION" or (is_open and start_ms is not None):
        exception_type = "SPECIAL_SESSION"
        starts_at = _ms_offset_to_local_time(start_ms)
        ends_at = _ms_offset_to_local_time(end_ms)
    else:
        exception_type = "CLOSED"
        starts_at = None
        ends_at = None

    return {
        "venue_code": exchange_code,
        "session_date": holiday_date,
        "exception_type": exception_type,
        "starts_at_local": starts_at,
        "ends_at_local": ends_at,
        "session_type": None,
        "description": description,
        "metadata": {
            "source": "legacy_market_holidays_migration",
            "legacy_holiday_id": int(holiday_id),
            "legacy_holiday_type": holiday_type,
        },
    }


def migrate(*, dry_run: bool = False) -> dict[str, int]:
    """Run the migration. Returns a counters dict.

    Counters: ``inserted_or_updated``, ``skipped_unknown_venue``,
    ``error``.
    """
    # Phase 4 venue tables must already exist.
    from database import venue_schedule_repo
    from database.instruments_repo import init_instrument_tables, venues_get

    init_instrument_tables()
    venue_schedule_repo.init_venue_schedule_tables()

    counters = {"inserted_or_updated": 0, "skipped_unknown_venue": 0, "error": 0}

    for row in _legacy_rows():
        kwargs = _legacy_to_exception_args(row)
        venue_code = kwargs["venue_code"]
        # The venues table needs a row before a calendar exception
        # FK can resolve. Skip cleanly if the venue isn't seeded.
        venue = venues_get(venue_code)
        if venue is None:
            logger.warning(
                "Skipping legacy holiday id=%s for venue=%r — venue row "
                "missing; run upgrade/seed_venue_schedule_defaults.py first.",
                kwargs["metadata"]["legacy_holiday_id"],
                venue_code,
            )
            counters["skipped_unknown_venue"] += 1
            continue

        if dry_run:
            counters["inserted_or_updated"] += 1
            continue

        try:
            venue_schedule_repo.upsert_calendar_exception(**kwargs)
            counters["inserted_or_updated"] += 1
        except Exception as e:
            logger.exception(
                "Failed to upsert calendar exception for venue=%r date=%s: %s",
                venue_code,
                kwargs["session_date"],
                e,
            )
            counters["error"] += 1

    logger.info(
        "Migration complete: inserted/updated=%(inserted_or_updated)d "
        "skipped_unknown_venue=%(skipped_unknown_venue)d errors=%(error)d",
        counters,
    )
    return counters


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Report what would happen without writing.",
    )
    args = parser.parse_args()
    counters = migrate(dry_run=args.dry_run)
    if counters["error"]:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
