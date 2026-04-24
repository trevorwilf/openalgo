"""Additive migration for broker_order_rules + broker_venue_session_overrides."""

from __future__ import annotations

from pathlib import Path

import pytest
from sqlalchemy import inspect

from database import broker_rules_repo


@pytest.fixture
def fresh_rules_db(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    db_file = tmp_path / "rules.db"
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{db_file}")
    broker_rules_repo._reset_engine_for_tests()
    yield db_file
    broker_rules_repo._reset_engine_for_tests()


def test_init_creates_both_tables(fresh_rules_db):
    broker_rules_repo.init_broker_rules_tables()
    engine = broker_rules_repo._get_engine()
    names = set(inspect(engine).get_table_names())
    assert "broker_order_rules" in names
    assert "broker_venue_session_overrides" in names


def test_init_is_idempotent(fresh_rules_db):
    broker_rules_repo.init_broker_rules_tables()
    # Second call must not raise and must not drop/recreate.
    broker_rules_repo.init_broker_rules_tables()
    engine = broker_rules_repo._get_engine()
    names = set(inspect(engine).get_table_names())
    assert "broker_order_rules" in names
    assert "broker_venue_session_overrides" in names


def test_rules_upsert_roundtrip(fresh_rules_db):
    broker_rules_repo.init_broker_rules_tables()
    row = broker_rules_repo.rules_upsert(
        broker_code="fake_us",
        venue_code="XNAS",
        asset_class="EQUITY",
        session_name="REGULAR",
        allowed_order_types=["MARKET", "LIMIT"],
        allowed_time_in_force=["DAY", "GTC"],
        allows_fractional=True,
        allows_short=True,
    )
    assert row.id is not None

    # Upserting the same qualifiers must update the existing row.
    row2 = broker_rules_repo.rules_upsert(
        broker_code="fake_us",
        venue_code="XNAS",
        asset_class="EQUITY",
        session_name="REGULAR",
        allowed_order_types=["MARKET"],
        allowed_time_in_force=["DAY"],
        allows_fractional=False,
        allows_short=False,
    )
    assert row2.id == row.id
    assert row2.allowed_order_types == ["MARKET"]
    assert row2.allows_fractional is False
