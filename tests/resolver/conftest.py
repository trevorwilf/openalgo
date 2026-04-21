"""Fixtures for the resolver test suite."""

from __future__ import annotations

from pathlib import Path

import pytest


@pytest.fixture
def fresh_db(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """Per-test SQLite file with the Phase 2a tables created."""
    db_file = tmp_path / "phase3a.db"
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{db_file}")

    from database import instruments_repo

    instruments_repo._reset_engine_for_tests()
    instruments_repo.init_instrument_tables()
    yield db_file
    instruments_repo._reset_engine_for_tests()


@pytest.fixture
def reset_default_resolver(monkeypatch):
    """Drop the module-level cached resolver so each test gets a fresh one.

    Tests that patch `database.token_db.get_token` before calling
    `get_resolver()` need the lambda inside the default resolver to see
    the patched function.
    """
    from services import instrument_resolver

    instrument_resolver.reset_default_resolver_for_tests()
    yield
    instrument_resolver.reset_default_resolver_for_tests()
