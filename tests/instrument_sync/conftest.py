"""Fixtures for the Phase 2b sync pipeline tests."""

from __future__ import annotations

from pathlib import Path

import pytest


FIXTURES_DIR = Path(__file__).parent / "fixtures"


@pytest.fixture
def fresh_db(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """Per-test SQLite file. Rebuilds the repo engine on setup."""
    db_file = tmp_path / "phase2b.db"
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{db_file}")

    from database import instruments_repo

    instruments_repo._reset_engine_for_tests()
    instruments_repo.init_instrument_tables()
    yield db_file
    instruments_repo._reset_engine_for_tests()


@pytest.fixture
def zerodha_fixture() -> Path:
    return FIXTURES_DIR / "zerodha_instruments_sample.csv"


@pytest.fixture
def delta_fixture() -> Path:
    return FIXTURES_DIR / "delta_products_sample.json"
