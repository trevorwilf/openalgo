"""v5 Phase 6 — chartink_strategies additive provider/region migration."""

from __future__ import annotations

from pathlib import Path

import pytest
from sqlalchemy import create_engine, inspect, text


@pytest.fixture
def fresh_chartink_db(tmp_path: Path, monkeypatch):
    """Per-test SQLite file pre-seeded with the legacy chartink schema."""
    db_file = tmp_path / "chartink.db"
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{db_file}")

    engine = create_engine(f"sqlite:///{db_file}")
    with engine.begin() as conn:
        conn.execute(
            text(
                "CREATE TABLE chartink_strategies ("
                "id INTEGER PRIMARY KEY AUTOINCREMENT, "
                "name VARCHAR(255) NOT NULL, "
                "webhook_id VARCHAR(36) NOT NULL UNIQUE, "
                "user_id VARCHAR(255) NOT NULL, "
                "is_active BOOLEAN, is_intraday BOOLEAN, "
                "start_time VARCHAR(5), end_time VARCHAR(5), "
                "squareoff_time VARCHAR(5), "
                "created_at DATETIME, updated_at DATETIME)"
            )
        )
        conn.execute(
            text(
                "INSERT INTO chartink_strategies "
                "(name, webhook_id, user_id, is_active, is_intraday) VALUES "
                "('legacy', 'wb-1', 'u1', 1, 1)"
            )
        )
    return db_file


def test_up_adds_columns_and_backfills(fresh_chartink_db):
    from upgrade.migrate_chartink_provider_columns import (
        add_chartink_provider_columns,
    )

    assert add_chartink_provider_columns()
    engine = create_engine(f"sqlite:///{fresh_chartink_db}")
    inspector = inspect(engine)
    cols = {c["name"] for c in inspector.get_columns("chartink_strategies")}
    assert "provider_code" in cols
    assert "region_code" in cols
    with engine.connect() as conn:
        row = conn.execute(
            text(
                "SELECT provider_code, region_code FROM chartink_strategies"
            )
        ).fetchone()
        assert row[0] == "chartink"
        assert row[1] == "india"


def test_up_is_idempotent(fresh_chartink_db):
    from upgrade.migrate_chartink_provider_columns import (
        add_chartink_provider_columns,
    )

    assert add_chartink_provider_columns()
    assert add_chartink_provider_columns()


def test_down_nulls_backfill_keeps_columns(fresh_chartink_db):
    from upgrade.migrate_chartink_provider_columns import (
        add_chartink_provider_columns,
        revert_chartink_provider_backfill,
    )

    add_chartink_provider_columns()
    assert revert_chartink_provider_backfill()
    engine = create_engine(f"sqlite:///{fresh_chartink_db}")
    inspector = inspect(engine)
    cols = {c["name"] for c in inspector.get_columns("chartink_strategies")}
    assert "provider_code" in cols
    assert "region_code" in cols
    with engine.connect() as conn:
        row = conn.execute(
            text("SELECT provider_code, region_code FROM chartink_strategies")
        ).fetchone()
        assert row[0] is None
        assert row[1] is None
