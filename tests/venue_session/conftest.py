"""Fixtures for Phase 4 venue session tests."""

from __future__ import annotations

from pathlib import Path

import pytest


@pytest.fixture
def seeded_db(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """Per-test SQLite with venues + schedule templates from the seed script."""
    db_file = tmp_path / "phase4.db"
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{db_file}")

    from database import instruments_repo, venue_schedule_repo
    from upgrade.seed_venue_schedule_defaults import seed_all

    instruments_repo._reset_engine_for_tests()
    instruments_repo.init_instrument_tables()
    venue_schedule_repo.init_venue_schedule_tables()
    stats = seed_all()
    yield {"db_file": db_file, **stats}
    instruments_repo._reset_engine_for_tests()


@pytest.fixture
def service(seeded_db):
    from services.venue_session_service import VenueSessionService

    return VenueSessionService()
