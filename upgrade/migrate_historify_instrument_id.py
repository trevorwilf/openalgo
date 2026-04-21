#!/usr/bin/env python3
"""Phase 3b migration — additive instrument_id column on historify tables.

Tables altered:
    market_data
    watchlist
    data_catalog
    job_items
    symbol_metadata

Each gets a nullable ``instrument_id VARCHAR`` column. An index is
added so any later instrument_id-keyed read path does not table-scan:

    idx_market_data_instrument_id       ON (instrument_id, interval, timestamp)
    idx_watchlist_instrument_id          ON (instrument_id)
    idx_data_catalog_instrument_id       ON (instrument_id, interval)
    idx_job_items_instrument_id          ON (instrument_id)
    idx_symbol_metadata_instrument_id    ON (instrument_id)

Idempotence
-----------
DuckDB supports ``ALTER TABLE ... ADD COLUMN IF NOT EXISTS`` and
``CREATE INDEX IF NOT EXISTS`` — both are a no-op when the target
already exists. Running this migration twice is safe.

Rollback
--------
Manual. Drop the indexes, then the columns — but DO NOT drop unless:
1. ``HISTORIFY_INSTRUMENT_ID_V2`` has never been enabled in prod, OR
2. every dual-written column can be re-derived from legacy (symbol,
   exchange) keys via the resolver (it can — that is the point).

Existing primary keys and unique constraints are NOT altered. No
existing column is dropped. Historify's read paths are unaffected by
this migration; they continue to use the legacy (symbol, exchange)
keys.

Usage::

    cd upgrade
    uv run migrate_historify_instrument_id.py

    # or from repo root:
    uv run upgrade/migrate_historify_instrument_id.py
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


# (table_name, index_name, index_columns)
_TABLE_INDEXES: list[tuple[str, str, tuple[str, ...]]] = [
    ("market_data", "idx_market_data_instrument_id", ("instrument_id", "interval", "timestamp")),
    ("watchlist", "idx_watchlist_instrument_id", ("instrument_id",)),
    ("data_catalog", "idx_data_catalog_instrument_id", ("instrument_id", "interval")),
    ("job_items", "idx_job_items_instrument_id", ("instrument_id",)),
    ("symbol_metadata", "idx_symbol_metadata_instrument_id", ("instrument_id",)),
]


def _existing_tables(conn) -> set[str]:
    rows = conn.execute(
        "SELECT table_name FROM information_schema.tables WHERE table_schema = 'main'"
    ).fetchall()
    return {r[0] for r in rows}


def migrate_historify_instrument_id() -> bool:
    """Run the migration against the configured Historify DuckDB. Idempotent."""
    from database.historify_db import get_connection

    try:
        with get_connection() as conn:
            tables_present = _existing_tables(conn)
            logger.info(
                "Phase 3b — historify tables present: %s",
                ", ".join(sorted(tables_present)),
            )
            for table, index, cols in _TABLE_INDEXES:
                if table not in tables_present:
                    logger.info("  skipping %s (table not present yet)", table)
                    continue
                # ADD COLUMN IF NOT EXISTS is a no-op when the column
                # already exists (DuckDB ≥ 0.7).
                conn.execute(
                    f"ALTER TABLE {table} ADD COLUMN IF NOT EXISTS "
                    f"instrument_id VARCHAR"
                )
                col_list = ", ".join(cols)
                conn.execute(
                    f"CREATE INDEX IF NOT EXISTS {index} ON {table} ({col_list})"
                )
                logger.info("  %s: column + index ensured", table)
        return True
    except Exception as e:
        logger.exception("Phase 3b migration failed: %s", e)
        return False


def main() -> int:
    logger.info("=" * 60)
    logger.info("OpenAlgo — Phase 3b Historify instrument_id migration")
    logger.info("=" * 60)
    logger.info("Adds nullable instrument_id columns and indexes. Idempotent.")
    logger.info("-" * 60)
    ok = migrate_historify_instrument_id()
    logger.info("-" * 60)
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
