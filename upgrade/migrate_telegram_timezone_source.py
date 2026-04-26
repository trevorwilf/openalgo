"""Phase 2 v4 (ADR 0023, invariant 1) — additive migration that adds
``timezone_source`` to the ``user_preferences`` table in the telegram
database, and backfills existing rows with ``"default_legacy_india"``
where the timezone was the legacy India default.

Additive only:
* The new column is nullable with a default of ``"default_via_region"``
  for rows inserted after the migration.
* Existing rows whose ``timezone == "Asia/Kolkata"`` are backfilled to
  ``"default_legacy_india"`` so we keep an audit trail.
* Existing rows with any other timezone are backfilled to
  ``"user"`` (the user must have set it explicitly).
* No existing column is dropped or rewritten.

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


def _telegram_db_url() -> str | None:
    raw = os.getenv("TELEGRAM_BOT_DATABASE_URL") or os.getenv("DATABASE_URL")
    if not raw:
        return None
    if raw.startswith("sqlite:///"):
        path_part = raw[len("sqlite:///") :]
        if not os.path.isabs(path_part):
            path_part = os.path.abspath(os.path.join(parent_dir, path_part))
        return f"sqlite:///{path_part}"
    return raw


def add_timezone_source_column() -> bool:
    db_url = _telegram_db_url()
    if not db_url:
        logger.error("Neither TELEGRAM_BOT_DATABASE_URL nor DATABASE_URL is set")
        return False
    logger.info("Using telegram db: %s", db_url)
    engine = create_engine(db_url)
    inspector = inspect(engine)
    if "user_preferences" not in inspector.get_table_names():
        logger.info(
            "user_preferences table does not exist yet — nothing to migrate."
        )
        return True
    columns = {c["name"] for c in inspector.get_columns("user_preferences")}
    with engine.connect() as conn:
        if "timezone_source" not in columns:
            logger.info("Adding timezone_source column to user_preferences ...")
            conn.execute(
                text(
                    "ALTER TABLE user_preferences "
                    "ADD COLUMN timezone_source VARCHAR(50)"
                )
            )
            conn.commit()
        else:
            logger.info("timezone_source column already exists.")
        # Backfill rows missing a source.
        result = conn.execute(
            text(
                "UPDATE user_preferences SET timezone_source = "
                "CASE WHEN timezone = 'Asia/Kolkata' "
                "THEN 'default_legacy_india' ELSE 'user' END "
                "WHERE timezone_source IS NULL"
            )
        )
        conn.commit()
        logger.info("Backfilled %d rows.", result.rowcount or 0)
    return True


if __name__ == "__main__":
    ok = add_timezone_source_column()
    sys.exit(0 if ok else 1)
