"""The Phase 2b runner must never touch symtoken, even when run against
a DB that carries legacy symtoken rows. Confirms invariant #1.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from services.instrument_sync_adapters.delta_adapter import DeltaAdapter
from services.instrument_sync_adapters.zerodha_adapter import ZerodhaAdapter
from services.instrument_sync_service import InstrumentSyncRunner


@pytest.fixture
def coexist_db(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """A DB that already has a legacy symtoken with rows, PLUS the
    Phase 2a tables created. Represents the real post-upgrade shape."""
    db_file = tmp_path / "coexist.db"

    # Seed symtoken with two rows
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
        INSERT INTO symtoken (symbol, brsymbol, exchange, token)
        VALUES ('INFY', 'INFY-EQ', 'NSE', '408065');
        """
    )
    conn.commit()
    conn.close()

    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{db_file}")
    from database import instruments_repo

    instruments_repo._reset_engine_for_tests()
    instruments_repo.init_instrument_tables()
    yield db_file
    instruments_repo._reset_engine_for_tests()


def _snapshot_symtoken(db_file: Path) -> tuple[int, list[tuple]]:
    conn = sqlite3.connect(db_file)
    try:
        count = conn.execute("SELECT COUNT(*) FROM symtoken").fetchone()[0]
        rows = conn.execute("SELECT * FROM symtoken ORDER BY id").fetchall()
    finally:
        conn.close()
    return count, rows


def test_zerodha_sync_does_not_touch_symtoken(
    coexist_db: Path, zerodha_fixture: Path
) -> None:
    pre_count, pre_rows = _snapshot_symtoken(coexist_db)
    InstrumentSyncRunner().run(ZerodhaAdapter(csv_path=zerodha_fixture))
    post_count, post_rows = _snapshot_symtoken(coexist_db)
    assert pre_count == post_count
    assert pre_rows == post_rows


def test_delta_sync_does_not_touch_symtoken(
    coexist_db: Path, delta_fixture: Path
) -> None:
    pre_count, pre_rows = _snapshot_symtoken(coexist_db)
    InstrumentSyncRunner().run(DeltaAdapter(json_path=delta_fixture))
    post_count, post_rows = _snapshot_symtoken(coexist_db)
    assert pre_count == post_count
    assert pre_rows == post_rows


def test_coexistence_run_leaves_symtoken_untouched(
    coexist_db: Path, zerodha_fixture: Path, delta_fixture: Path
) -> None:
    """Both adapters in sequence — symtoken still unchanged."""
    pre_count, pre_rows = _snapshot_symtoken(coexist_db)
    InstrumentSyncRunner().run(ZerodhaAdapter(csv_path=zerodha_fixture))
    InstrumentSyncRunner().run(DeltaAdapter(json_path=delta_fixture))
    post_count, post_rows = _snapshot_symtoken(coexist_db)
    assert pre_count == post_count
    assert pre_rows == post_rows
