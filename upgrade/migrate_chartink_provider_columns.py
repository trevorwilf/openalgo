"""v5 Phase 6 (ADR 0028 follow-on) — additive migration that adds
``provider_code`` and ``region_code`` columns to the
``chartink_strategies`` table.

Additive only (D-3, v4 invariant 9):
* The new columns are nullable; existing rows keep ``NULL``.
* Conditional backfill: every existing chartink strategy was India
  (Chartink is India-only today), so legacy rows get
  ``provider_code='chartink'``, ``region_code='india'``. Ambiguous
  rows would stay ``NULL`` if any other provider were active (today
  none is).
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


_TABLE = "chartink_strategies"
_COLS: tuple[tuple[str, str], ...] = (
    ("provider_code", "VARCHAR(50)"),
    ("region_code", "VARCHAR(20)"),
)


def _db_url() -> str | None:
    raw = os.getenv("DATABASE_URL")
    if not raw:
        return None
    if raw.startswith("sqlite:///"):
        path_part = raw[len("sqlite:///") :]
        if not os.path.isabs(path_part):
            path_part = os.path.abspath(os.path.join(parent_dir, path_part))
        return f"sqlite:///{path_part}"
    return raw


def add_chartink_provider_columns() -> bool:
    db_url = _db_url()
    if not db_url:
        logger.error("DATABASE_URL is not set")
        return False
    logger.info("Using db: %s", db_url)
    engine = create_engine(db_url)
    inspector = inspect(engine)
    if _TABLE not in inspector.get_table_names():
        logger.info("table %s does not exist yet — nothing to migrate.", _TABLE)
        return True
    existing_cols = {c["name"] for c in inspector.get_columns(_TABLE)}
    with engine.connect() as conn:
        for name, sql_type in _COLS:
            if name not in existing_cols:
                logger.info("ALTER TABLE %s ADD COLUMN %s %s", _TABLE, name, sql_type)
                conn.execute(text(f"ALTER TABLE {_TABLE} ADD COLUMN {name} {sql_type}"))
                conn.commit()
            else:
                logger.info("%s.%s already exists — skip", _TABLE, name)
        result = conn.execute(
            text(
                f"UPDATE {_TABLE} SET provider_code='chartink', region_code='india' "
                f"WHERE provider_code IS NULL AND region_code IS NULL"
            )
        )
        conn.commit()
        logger.info("Backfilled %d rows.", result.rowcount or 0)
    return True


def revert_chartink_provider_backfill() -> bool:
    """Down-migration: NULL the values we backfilled. Columns stay
    (D-3 — no DROP)."""
    db_url = _db_url()
    if not db_url:
        return False
    engine = create_engine(db_url)
    inspector = inspect(engine)
    if _TABLE not in inspector.get_table_names():
        return True
    with engine.connect() as conn:
        existing_cols = {c["name"] for c in inspector.get_columns(_TABLE)}
        if not all(name in existing_cols for name, _ in _COLS):
            return True
        result = conn.execute(
            text(
                f"UPDATE {_TABLE} SET provider_code=NULL, region_code=NULL "
                f"WHERE provider_code='chartink' AND region_code='india'"
            )
        )
        conn.commit()
        logger.info("Reverted backfill on %d rows.", result.rowcount or 0)
    return True


if __name__ == "__main__":
    ok = add_chartink_provider_columns()
    sys.exit(0 if ok else 1)
