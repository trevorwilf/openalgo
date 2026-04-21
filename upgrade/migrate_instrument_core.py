#!/usr/bin/env python3
"""Phase 2a migration — additive instrument-universe tables.

Creates five new tables the market-agnostic refactor depends on:

* ``venues`` — one row per execution venue
* ``instruments`` — canonical instrument rows keyed by UUID
* ``instrument_identifiers`` — alternative IDs (ISIN, FIGI, broker tokens)
* ``broker_instrument_map`` — fast broker-symbol → instrument lookup
* ``instrument_sync_runs`` — provenance for broker-map sync runs

All SQL is additive. The `symtoken` table is not touched, not altered,
and not referenced by any FK created here. Per ADR 0001 and the
invariants in CLAUDE.md, nothing under `services/`, `blueprints/`, or
`broker/` may consume these tables yet — Phase 2b onward wires
consumers behind the `INSTRUMENT_CORE_V2` feature flag.

Idempotence
-----------
`database.instruments_repo.init_instrument_tables` uses SQLAlchemy's
`Base.metadata.create_all`, which emits `CREATE TABLE IF NOT EXISTS`
under the hood for every table in the Phase 2a metadata. Running the
migration against a DB that already has some of the tables is a no-op
for those tables; running it against a fresh DB creates them all.

Rollback
--------
Rollback is manual and should only be done when `INSTRUMENT_CORE_V2`
has never been enabled in production, OR when all Phase 2a tables are
verified empty. Drop order must respect FK dependencies:

    DROP TABLE IF EXISTS broker_instrument_map;
    DROP TABLE IF EXISTS instrument_identifiers;
    DROP TABLE IF EXISTS instrument_sync_runs;
    DROP TABLE IF EXISTS instruments;
    DROP TABLE IF EXISTS venues;

`symtoken` is NOT included in either direction — it is untouched.

Usage::

    cd upgrade
    uv run migrate_instrument_core.py

    # Or from project root:
    uv run upgrade/migrate_instrument_core.py
"""

from __future__ import annotations

import os
import sys

# Add project root to path so database.* imports resolve.
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dotenv import load_dotenv

# Load .env from project root before anything that reads env vars.
env_path = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), ".env"
)
load_dotenv(env_path)

from sqlalchemy import inspect  # noqa: E402

from utils.logging import get_logger  # noqa: E402

logger = get_logger(__name__)

NEW_TABLES = [
    "venues",
    "instruments",
    "instrument_identifiers",
    "broker_instrument_map",
    "instrument_sync_runs",
]


def migrate_instrument_core() -> bool:
    """Run the Phase 2a migration. Idempotent.

    Returns True on success, False on any error.
    """
    # Import here (not top-level) so the migration picks up the DATABASE_URL
    # that load_dotenv just set.
    from database.instruments_repo import (
        _reset_engine_for_tests,
        get_engine,
        init_instrument_tables,
    )

    # Rebuild the engine with the current env to avoid reusing any cached
    # engine from a prior import path.
    _reset_engine_for_tests()
    engine = get_engine()

    inspector = inspect(engine)
    existing = set(inspector.get_table_names())
    pre_missing = [t for t in NEW_TABLES if t not in existing]
    pre_present = [t for t in NEW_TABLES if t in existing]

    if pre_missing:
        logger.info(
            "Phase 2a — creating tables: %s", ", ".join(pre_missing)
        )
    if pre_present:
        logger.info(
            "Phase 2a — already present (skipping): %s",
            ", ".join(pre_present),
        )

    try:
        init_instrument_tables(engine)
    except Exception as e:
        logger.exception("Phase 2a migration failed: %s", e)
        return False

    # Verify
    inspector = inspect(engine)
    final = set(inspector.get_table_names())
    still_missing = [t for t in NEW_TABLES if t not in final]
    if still_missing:
        logger.error(
            "Phase 2a verification failed — missing tables: %s",
            ", ".join(still_missing),
        )
        return False

    # Explicit safety check: symtoken must remain present iff it was
    # present before, with no column changes. Only the existence check
    # is cheap enough to run here; a schema-diff would require a SAVEPOINT.
    if "symtoken" in existing and "symtoken" not in final:
        logger.error(
            "Phase 2a FATAL — symtoken disappeared between start and end "
            "of migration. Restore from backup."
        )
        return False

    logger.info(
        "Phase 2a migration complete. Tables present: %s",
        ", ".join(sorted(final & set(NEW_TABLES))),
    )
    return True


def main() -> int:
    logger.info("=" * 60)
    logger.info("OpenAlgo — Phase 2a instrument-universe migration")
    logger.info("=" * 60)
    logger.info(
        "Adds 5 additive tables. symtoken is not touched. Idempotent."
    )
    logger.info("-" * 60)
    ok = migrate_instrument_core()
    logger.info("-" * 60)
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
