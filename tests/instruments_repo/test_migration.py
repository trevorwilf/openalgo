"""Migration idempotence + symtoken is left untouched."""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest
from sqlalchemy import create_engine, inspect


PHASE_2A_TABLES = {
    "venues",
    "instruments",
    "instrument_identifiers",
    "broker_instrument_map",
    "instrument_sync_runs",
}


def _tables(db_file: Path) -> set[str]:
    engine = create_engine(f"sqlite:///{db_file}")
    try:
        return set(inspect(engine).get_table_names())
    finally:
        engine.dispose()


def test_migration_creates_all_tables(fresh_db: Path) -> None:
    tables = _tables(fresh_db)
    assert PHASE_2A_TABLES.issubset(tables)


def test_migration_is_idempotent(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    db_file = tmp_path / "idemp.db"
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{db_file}")

    from database import instruments_repo

    instruments_repo._reset_engine_for_tests()
    instruments_repo.init_instrument_tables()
    first = _tables(db_file)

    # Running it again must not error or change the table set.
    instruments_repo.init_instrument_tables()
    second = _tables(db_file)

    assert first == second
    assert PHASE_2A_TABLES.issubset(second)
    instruments_repo._reset_engine_for_tests()


def test_migration_does_not_touch_symtoken(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Pre-seed a DB with a legacy symtoken table, run the migration, assert
    symtoken rows and schema are byte-identical after."""
    db_file = tmp_path / "coexist.db"

    # Hand-roll a minimal symtoken with one row.
    conn = sqlite3.connect(db_file)
    conn.executescript(
        """
        CREATE TABLE symtoken (
            id INTEGER PRIMARY KEY,
            symbol TEXT NOT NULL,
            brsymbol TEXT NOT NULL,
            exchange TEXT,
            token TEXT
        );
        INSERT INTO symtoken (symbol, brsymbol, exchange, token)
        VALUES ('RELIANCE', 'RELIANCE-EQ', 'NSE', '738561');
        """
    )
    conn.commit()
    conn.close()

    # Capture pre-migration state.
    conn = sqlite3.connect(db_file)
    pre_rows = conn.execute("SELECT * FROM symtoken").fetchall()
    pre_schema = conn.execute(
        "SELECT sql FROM sqlite_master WHERE type='table' AND name='symtoken'"
    ).fetchone()[0]
    conn.close()

    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{db_file}")
    from database import instruments_repo

    instruments_repo._reset_engine_for_tests()
    instruments_repo.init_instrument_tables()
    instruments_repo._reset_engine_for_tests()

    # Verify symtoken unchanged.
    conn = sqlite3.connect(db_file)
    post_rows = conn.execute("SELECT * FROM symtoken").fetchall()
    post_schema = conn.execute(
        "SELECT sql FROM sqlite_master WHERE type='table' AND name='symtoken'"
    ).fetchone()[0]
    post_tables = {
        r[0]
        for r in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        ).fetchall()
    }
    conn.close()

    assert pre_rows == post_rows, "symtoken rows changed"
    assert pre_schema == post_schema, "symtoken schema changed"
    assert PHASE_2A_TABLES.issubset(post_tables)
    assert "symtoken" in post_tables
