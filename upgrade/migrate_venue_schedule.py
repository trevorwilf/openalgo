#!/usr/bin/env python3
"""Phase 4 migration — venue_schedule_templates + venue_calendar_exceptions.

Both tables are additive. They FK to the Phase 2a ``venues`` table but
do not alter it. Legacy ``market_calendar_db`` tables
(``market_holidays``, ``market_holiday_exchanges``, ``market_timings``)
are untouched.

Idempotence
-----------
``Base.metadata.create_all`` emits ``CREATE TABLE IF NOT EXISTS`` for
every table in the Phase 2a+4 metadata. Running this migration twice
is a no-op for existing tables.

Rollback
--------
Manual. Drop the two new tables in FK-safe order:

    DROP TABLE IF EXISTS venue_calendar_exceptions;
    DROP TABLE IF EXISTS venue_schedule_templates;

``venues`` is untouched in either direction.

Usage::

    cd upgrade
    uv run migrate_venue_schedule.py

    # or from repo root:
    uv run upgrade/migrate_venue_schedule.py
"""

from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dotenv import load_dotenv  # noqa: E402

env_path = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), ".env"
)
load_dotenv(env_path)

from utils.logging import get_logger  # noqa: E402

logger = get_logger(__name__)


def migrate_venue_schedule() -> bool:
    """Create the two Phase 4 tables. Idempotent."""
    from database.instruments_repo import _reset_engine_for_tests
    from database.venue_schedule_repo import init_venue_schedule_tables

    _reset_engine_for_tests()
    try:
        init_venue_schedule_tables()
        logger.info("Phase 4 venue schedule tables ensured.")
        return True
    except Exception as e:
        logger.exception("Phase 4 migration failed: %s", e)
        return False


def main() -> int:
    logger.info("=" * 60)
    logger.info("OpenAlgo — Phase 4 venue schedule migration")
    logger.info("=" * 60)
    logger.info("Adds venue_schedule_templates + venue_calendar_exceptions.")
    logger.info("-" * 60)
    ok = migrate_venue_schedule()
    logger.info("-" * 60)
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
