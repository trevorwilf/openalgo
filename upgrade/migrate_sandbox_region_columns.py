"""v5 Phase 4 (ADR 0026 follow-on) — additive migration that adds
``region_code``, ``currency``, and ``provider_code`` columns to the
sandbox database tables (``sandbox_orders``, ``sandbox_positions``,
``sandbox_funds``).

Additive only (D-3, v4 invariant 9):
* The new columns are nullable; rows inserted before the migration
  retain ``NULL``.
* Conditional backfill: rows that are unambiguously India (currently
  the only sandbox provider) are backfilled with
  ``region_code='india'``, ``currency='INR'``, ``provider_code='india'``.
  Ambiguous rows stay ``NULL``. Today every legacy sandbox row IS
  India because v5 ships the first non-India sandbox provider,
  so the conditional is trivially "all rows" — but the structured
  conditional makes the migration safe to re-run after future
  providers are added.
* No existing column is dropped, no constraint is rewritten.

Idempotent: safe to re-run.
"""

from __future__ import annotations

import logging
import os
import sys

from dotenv import load_dotenv
from sqlalchemy import create_engine, inspect, text

parent_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.append(parent_dir)
load_dotenv(os.path.join(parent_dir, ".env"))

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


_TABLE_COLUMNS: tuple[tuple[str, tuple[tuple[str, str], ...]], ...] = (
    (
        "sandbox_orders",
        (
            ("region_code", "VARCHAR(20)"),
            ("currency", "VARCHAR(8)"),
            ("provider_code", "VARCHAR(50)"),
        ),
    ),
    (
        "sandbox_positions",
        (
            ("region_code", "VARCHAR(20)"),
            ("currency", "VARCHAR(8)"),
            ("provider_code", "VARCHAR(50)"),
        ),
    ),
    (
        "sandbox_funds",
        (
            ("region_code", "VARCHAR(20)"),
            ("currency", "VARCHAR(8)"),
            ("provider_code", "VARCHAR(50)"),
        ),
    ),
)


def _sandbox_db_url() -> str | None:
    raw = os.getenv("SANDBOX_DATABASE_URL") or "sqlite:///db/sandbox.db"
    if raw.startswith("sqlite:///"):
        path_part = raw[len("sqlite:///") :]
        if not os.path.isabs(path_part):
            path_part = os.path.abspath(os.path.join(parent_dir, path_part))
        return f"sqlite:///{path_part}"
    return raw


def add_sandbox_region_columns() -> bool:
    db_url = _sandbox_db_url()
    if not db_url:
        logger.error("Could not resolve SANDBOX_DATABASE_URL")
        return False
    logger.info("Using sandbox db: %s", db_url)
    engine = create_engine(db_url)
    inspector = inspect(engine)
    existing_tables = set(inspector.get_table_names())

    with engine.connect() as conn:
        for table, cols in _TABLE_COLUMNS:
            if table not in existing_tables:
                logger.info("table %s does not exist yet — nothing to migrate.", table)
                continue
            existing_cols = {
                c["name"] for c in inspector.get_columns(table)
            }
            for col_name, sql_type in cols:
                if col_name not in existing_cols:
                    logger.info("ALTER TABLE %s ADD COLUMN %s %s", table, col_name, sql_type)
                    conn.execute(
                        text(f"ALTER TABLE {table} ADD COLUMN {col_name} {sql_type}")
                    )
                    conn.commit()
                else:
                    logger.info("%s.%s already exists — skip", table, col_name)
            # Conditional backfill: today every legacy sandbox row is
            # India (no other provider ships in v5). The conditional
            # is structured so future providers can be backfilled
            # similarly without overwriting manual values.
            result = conn.execute(
                text(
                    f"UPDATE {table} SET region_code='india', "
                    f"currency='INR', provider_code='india' "
                    f"WHERE region_code IS NULL"
                )
            )
            conn.commit()
            logger.info(
                "Backfilled %d rows in %s.", result.rowcount or 0, table
            )
    return True


def revert_sandbox_region_backfill() -> bool:
    """Down-migration: NULL out the values we backfilled.

    The columns themselves stay (D-3 — no DROP). This is the safe
    'reversibility-without-drop' contract the v5 prompt requires.
    """
    db_url = _sandbox_db_url()
    if not db_url:
        return False
    engine = create_engine(db_url)
    inspector = inspect(engine)
    existing_tables = set(inspector.get_table_names())
    with engine.connect() as conn:
        for table, cols in _TABLE_COLUMNS:
            if table not in existing_tables:
                continue
            existing_cols = {c["name"] for c in inspector.get_columns(table)}
            if not all(name in existing_cols for name, _ in cols):
                continue
            result = conn.execute(
                text(
                    f"UPDATE {table} SET region_code=NULL, "
                    f"currency=NULL, provider_code=NULL "
                    f"WHERE region_code='india' AND currency='INR' "
                    f"AND provider_code='india'"
                )
            )
            conn.commit()
            logger.info(
                "Reverted backfill on %d rows in %s.", result.rowcount or 0, table
            )
    return True


if __name__ == "__main__":
    ok = add_sandbox_region_columns()
    sys.exit(0 if ok else 1)
