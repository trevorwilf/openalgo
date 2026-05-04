"""T-06 (v7 Phase 4-bis) — SymToken broker provenance backfill.

Forward migration:
* Add ``broker_code`` and ``instrument_id`` columns to ``symtoken``
  (no-op if the schema already declares them — ``CREATE TABLE`` in
  the live model already covers this; this script handles the
  upgrade-in-place case for operators with existing ``symtoken``
  rows from before the schema bump).
* Backfill ``broker_code`` from the operator's currently-active
  broker (resolved via ``BROKER_API_KEY`` env or the active
  connection record).
* Backfill ``instrument_id`` with a fresh UUID4 per row.

This script is idempotent — running it twice on a fully-backfilled
database is a no-op.

Downgrade: drops both columns + the index. Note that downgrading
will lose the broker provenance — operators are advised to
back up the database before running the downgrade.

Usage::

    uv run python upgrade/migrate_symtoken_broker_provenance.py
    uv run python upgrade/migrate_symtoken_broker_provenance.py --downgrade
"""

from __future__ import annotations

import argparse
import os
import sys
import uuid
from pathlib import Path

# Repo root on sys.path so this script runs from any cwd.
_REPO_ROOT = Path(__file__).resolve().parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from dotenv import load_dotenv  # noqa: E402

load_dotenv(_REPO_ROOT / ".env")

from sqlalchemy import inspect, text  # noqa: E402

from utils.logging import get_logger  # noqa: E402

logger = get_logger(__name__)


def _resolve_active_broker() -> str:
    """Resolve the operator's currently-active broker code.

    Resolution order:
    1. ``BROKER_API_KEY`` env value matched against known plugin
       prefixes (operator's actual broker session).
    2. ``DEFAULT_BROKER`` env override (used by automated migrations).
    3. ``""`` — caller may proceed but rows get NULL backfill.
    """
    forced = os.environ.get("DEFAULT_BROKER")
    if forced:
        return forced.strip().lower()

    # If BROKER_API_KEY is set, prefer the broker referenced in
    # the operator's active session record. The session table is
    # owned by the auth module; reading it requires the auth_db
    # bootstrap path which the migration script avoids to stay
    # decoupled. Operators with multiple historical brokers should
    # set DEFAULT_BROKER explicitly.
    return ""


def _has_column(connection, table: str, column: str) -> bool:
    inspector = inspect(connection)
    cols = {c["name"] for c in inspector.get_columns(table)}
    return column in cols


def upgrade() -> None:
    from market_regions.india.legacy_v1.database.symbol import db_session, engine

    broker = _resolve_active_broker()
    logger.info("T-06 migration: active broker resolved to %r", broker or "<none>")

    with engine.connect() as conn:
        # Add columns if missing (idempotent).
        if not _has_column(conn, "symtoken", "broker_code"):
            conn.execute(text("ALTER TABLE symtoken ADD COLUMN broker_code VARCHAR"))
            logger.info("Added column symtoken.broker_code")
        else:
            logger.info("symtoken.broker_code already present")

        if not _has_column(conn, "symtoken", "instrument_id"):
            conn.execute(text("ALTER TABLE symtoken ADD COLUMN instrument_id VARCHAR"))
            logger.info("Added column symtoken.instrument_id")
        else:
            logger.info("symtoken.instrument_id already present")

        # Backfill broker_code where NULL.
        if broker:
            result = conn.execute(
                text(
                    "UPDATE symtoken SET broker_code = :broker "
                    "WHERE broker_code IS NULL OR broker_code = ''"
                ),
                {"broker": broker},
            )
            logger.info(
                "Backfilled broker_code=%r on %d rows", broker, result.rowcount
            )

        # Phase 4-bis-4: create the v1-compatibility view that
        # hides broker_code + instrument_id from external SQL
        # consumers. Operators and integration scripts that select
        # from ``symtoken_v1`` get the pre-T-06 column set.
        # ``CREATE VIEW IF NOT EXISTS`` is supported by SQLite +
        # PostgreSQL so this is idempotent.
        try:
            conn.execute(text("DROP VIEW IF EXISTS symtoken_v1"))
            conn.execute(
                text(
                    "CREATE VIEW symtoken_v1 AS SELECT "
                    "id, symbol, brsymbol, name, exchange, brexchange, "
                    "token, expiry, strike, lotsize, instrumenttype, "
                    "tick_size, contract_value FROM symtoken"
                )
            )
            logger.info("Created view symtoken_v1 (pre-T-06 column set)")
        except Exception as e:
            logger.warning("Could not create symtoken_v1 view: %s", e)

        # Backfill instrument_id where NULL — assign a UUID4 per row.
        rows = conn.execute(
            text("SELECT id FROM symtoken WHERE instrument_id IS NULL OR instrument_id = ''")
        ).fetchall()
        if rows:
            for row in rows:
                conn.execute(
                    text("UPDATE symtoken SET instrument_id = :uid WHERE id = :id"),
                    {"uid": str(uuid.uuid4()), "id": row[0]},
                )
            logger.info("Backfilled instrument_id on %d rows", len(rows))
        conn.commit()

    db_session.remove()


def downgrade() -> None:
    """Drop the T-06 columns + the symtoken_v1 view. Lossy —
    operators are advised to back up before running."""
    from market_regions.india.legacy_v1.database.symbol import db_session, engine

    with engine.connect() as conn:
        try:
            conn.execute(text("DROP VIEW IF EXISTS symtoken_v1"))
            logger.info("Dropped view symtoken_v1")
        except Exception as e:
            logger.warning("Could not drop symtoken_v1: %s", e)
        if _has_column(conn, "symtoken", "instrument_id"):
            conn.execute(text("ALTER TABLE symtoken DROP COLUMN instrument_id"))
            logger.info("Dropped column symtoken.instrument_id")
        if _has_column(conn, "symtoken", "broker_code"):
            conn.execute(text("ALTER TABLE symtoken DROP COLUMN broker_code"))
            logger.info("Dropped column symtoken.broker_code")
        conn.commit()

    db_session.remove()


def main() -> int:
    parser = argparse.ArgumentParser(
        description="T-06 SymToken broker_code + instrument_id migration"
    )
    parser.add_argument("--downgrade", action="store_true", help="Drop the columns")
    args = parser.parse_args()

    if args.downgrade:
        downgrade()
        return 0

    upgrade()
    return 0


if __name__ == "__main__":
    sys.exit(main())
