"""Alpaca rule-seed idempotency."""

from __future__ import annotations

from pathlib import Path

import pytest

from broker.alpaca.sync.seed_rules import BROKER_CODE, seed_alpaca_rules
from database import broker_rules_repo


@pytest.fixture
def fresh_rules_db(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    db_file = tmp_path / "rules.db"
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{db_file}")
    broker_rules_repo._reset_engine_for_tests()
    yield db_file
    broker_rules_repo._reset_engine_for_tests()


def test_seed_creates_expected_rule(fresh_rules_db):
    seed_alpaca_rules()
    rows = broker_rules_repo.rules_list_for(BROKER_CODE)
    assert len(rows) == 1
    row = rows[0]
    assert row.asset_class == "EQUITY"
    assert row.session == "REGULAR"
    assert set(row.allowed_order_types) == {"MARKET", "LIMIT"}
    assert set(row.allowed_time_in_force) == {"DAY", "GTC"}
    assert row.allows_fractional is True
    assert row.allows_notional is True


def test_seed_is_idempotent(fresh_rules_db):
    seed_alpaca_rules()
    seed_alpaca_rules()
    rows = broker_rules_repo.rules_list_for(BROKER_CODE)
    assert len(rows) == 1
