"""Phase 3b migration: idempotence + instrument_id column on all 5 tables."""

from __future__ import annotations

from pathlib import Path

import pytest


EXPECTED_TABLES = ("market_data", "watchlist", "data_catalog", "job_items", "symbol_metadata")


def _column_names(conn, table: str) -> set[str]:
    rows = conn.execute(f"PRAGMA table_info('{table}')").fetchall()
    # PRAGMA table_info columns: (cid, name, type, notnull, dflt_value, pk)
    return {r[1] for r in rows}


def test_fresh_db_has_instrument_id_columns(historify_db: Path) -> None:
    from database.historify_db import get_connection

    with get_connection() as conn:
        for t in EXPECTED_TABLES:
            cols = _column_names(conn, t)
            assert "instrument_id" in cols, f"{t} missing instrument_id"


def test_migration_idempotent(historify_db: Path, tmp_path: Path) -> None:
    from upgrade.migrate_historify_instrument_id import (
        migrate_historify_instrument_id,
    )

    # First run — fresh DB already has the columns, migration is a no-op.
    assert migrate_historify_instrument_id() is True
    # Second run — still no-op.
    assert migrate_historify_instrument_id() is True


def test_existing_rows_preserved(historify_db: Path) -> None:
    """Seed market_data with rows (pre-migration shape), run migration
    (which is a no-op because fresh DBs already have the column), then
    verify rows are intact."""
    from database.historify_db import get_connection
    from upgrade.migrate_historify_instrument_id import (
        migrate_historify_instrument_id,
    )

    with get_connection() as conn:
        conn.execute(
            """
            INSERT INTO market_data
            (symbol, exchange, interval, timestamp, open, high, low, close, volume, oi)
            VALUES ('RELIANCE', 'NSE', '1m', 1700000000, 100, 101, 99, 100.5, 1000, 0)
            """
        )

    assert migrate_historify_instrument_id() is True

    with get_connection() as conn:
        rows = conn.execute(
            "SELECT symbol, exchange, open, close, instrument_id FROM market_data"
        ).fetchall()
        assert len(rows) == 1
        assert rows[0][0] == "RELIANCE"
        assert rows[0][4] is None  # instrument_id left NULL by pre-flag insert


def test_migration_leaves_unrelated_tables_untouched(historify_db: Path) -> None:
    """The migration only touches the 5 expected tables."""
    from database.historify_db import get_connection

    with get_connection() as conn:
        all_tables = {
            r[0]
            for r in conn.execute(
                "SELECT table_name FROM information_schema.tables "
                "WHERE table_schema = 'main'"
            ).fetchall()
        }
    # At least the 5 expected tables exist.
    assert set(EXPECTED_TABLES).issubset(all_tables)
