"""Fixtures for Phase 3b historify tests.

Each test uses a per-test DuckDB file plus a per-test SQLite file for
the Phase 2a instrument tables. Resolver is wired to both.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest


@pytest.fixture
def historify_db(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Isolate the Historify DuckDB and initialize its schema."""
    duck_path = tmp_path / "phase3b_historify.duckdb"
    monkeypatch.setenv("HISTORIFY_DATABASE_PATH", str(duck_path))

    # The env var is consulted at import time; re-read module-level state.
    from database import historify_db as hdb

    # Monkeypatch HISTORIFY_DB_PATH so the connection picks up the tmp path.
    monkeypatch.setattr(hdb, "HISTORIFY_DB_PATH", str(duck_path))
    hdb.init_database()
    return duck_path


@pytest.fixture
def instruments_db(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Per-test SQLite file for Phase 2a instrument tables."""
    db_file = tmp_path / "phase3b_instruments.db"
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{db_file}")
    from database import instruments_repo

    instruments_repo._reset_engine_for_tests()
    instruments_repo.init_instrument_tables()
    yield db_file
    instruments_repo._reset_engine_for_tests()


@pytest.fixture
def reset_default_resolver():
    from services import instrument_resolver

    instrument_resolver.reset_default_resolver_for_tests()
    yield
    instrument_resolver.reset_default_resolver_for_tests()
