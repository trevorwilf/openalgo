"""Shared fixtures for service-level resolver parity tests."""

from __future__ import annotations

from pathlib import Path

import pytest


@pytest.fixture
def fresh_db(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """Per-test SQLite file with Phase 2a tables initialized."""
    db_file = tmp_path / "phase3a-services.db"
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
