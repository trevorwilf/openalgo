"""Fixtures for the instruments_repo test suite.

Each test gets a fresh file-backed SQLite DB under pytest's `tmp_path`.
We avoid `sqlite:///:memory:` because NullPool opens a new connection
per operation and in-memory DBs are per-connection — different
connections see different (empty) databases.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest


@pytest.fixture
def fresh_db(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """Isolate DATABASE_URL to a per-test SQLite file and reset the
    module-level engine/sessionmaker so the repo rebuilds for this DB.
    """
    db_file = tmp_path / "phase2a.db"
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{db_file}")

    # Reset repo caches so get_engine() rebuilds using the new env.
    from database import instruments_repo

    instruments_repo._reset_engine_for_tests()
    instruments_repo.init_instrument_tables()
    yield db_file
    instruments_repo._reset_engine_for_tests()
