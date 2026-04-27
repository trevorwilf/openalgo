"""v5 Phase 4 — additive sandbox region/currency/provider columns
migration tests.

Verifies:
* Up-migration adds the columns without dropping anything.
* Backfill correctly tags existing rows with region='india',
  currency='INR', provider_code='india'.
* Re-running the up-migration is idempotent.
* Down-migration NULLs the backfill but leaves the columns intact
  (D-3: no DROP).
"""

from __future__ import annotations

from pathlib import Path

import pytest
from sqlalchemy import create_engine, inspect, text


@pytest.fixture
def fresh_sandbox_db(tmp_path: Path, monkeypatch):
    """Per-test sandbox SQLite file pre-seeded with the legacy schema
    (sandbox_orders / sandbox_positions / sandbox_funds *without* the
    new columns)."""
    db_file = tmp_path / "sandbox.db"
    monkeypatch.setenv("SANDBOX_DATABASE_URL", f"sqlite:///{db_file}")

    # Create the legacy schema — minimal subset of columns the
    # migration touches; the migration is column-additive, so any
    # extra legacy columns it doesn't touch don't matter.
    engine = create_engine(f"sqlite:///{db_file}")
    with engine.begin() as conn:
        conn.execute(
            text(
                "CREATE TABLE sandbox_orders ("
                "id INTEGER PRIMARY KEY AUTOINCREMENT, "
                "orderid VARCHAR(50) NOT NULL UNIQUE, "
                "user_id VARCHAR(50) NOT NULL, "
                "symbol VARCHAR(50) NOT NULL, "
                "exchange VARCHAR(20) NOT NULL, "
                "action VARCHAR(10), quantity INTEGER, "
                "price_type VARCHAR(20), product VARCHAR(20), "
                "order_status VARCHAR(20), pending_quantity INTEGER, "
                "order_timestamp DATETIME, update_timestamp DATETIME)"
            )
        )
        conn.execute(
            text(
                "CREATE TABLE sandbox_positions ("
                "id INTEGER PRIMARY KEY AUTOINCREMENT, "
                "user_id VARCHAR(50), symbol VARCHAR(50), exchange VARCHAR(20), "
                "product VARCHAR(20), quantity INTEGER, average_price DECIMAL(10,2))"
            )
        )
        conn.execute(
            text(
                "CREATE TABLE sandbox_funds ("
                "id INTEGER PRIMARY KEY AUTOINCREMENT, "
                "user_id VARCHAR(50) UNIQUE, total_capital DECIMAL(15,2), "
                "available_balance DECIMAL(15,2), used_margin DECIMAL(15,2), "
                "last_reset_date DATETIME)"
            )
        )
        # Insert an existing row in each table so backfill has work to do.
        conn.execute(
            text(
                "INSERT INTO sandbox_orders "
                "(orderid, user_id, symbol, exchange, action, quantity, "
                "price_type, product, order_status, pending_quantity) VALUES "
                "('legacy-1', 'u1', 'INFY', 'NSE', 'BUY', 1, 'MARKET', 'MIS', 'open', 1)"
            )
        )
        conn.execute(
            text(
                "INSERT INTO sandbox_positions "
                "(user_id, symbol, exchange, product, quantity, average_price) "
                "VALUES ('u1', 'INFY', 'NSE', 'MIS', 1, 1500.00)"
            )
        )
        conn.execute(
            text(
                "INSERT INTO sandbox_funds "
                "(user_id, total_capital, available_balance, used_margin, last_reset_date) "
                "VALUES ('u1', 1000000.00, 1000000.00, 0.00, '2026-04-15')"
            )
        )
    return db_file


def test_up_migration_adds_columns_and_backfills(fresh_sandbox_db):
    from upgrade.migrate_sandbox_region_columns import add_sandbox_region_columns

    assert add_sandbox_region_columns()
    # Verify columns exist
    engine = create_engine(f"sqlite:///{fresh_sandbox_db}")
    inspector = inspect(engine)
    for table in ("sandbox_orders", "sandbox_positions", "sandbox_funds"):
        cols = {c["name"] for c in inspector.get_columns(table)}
        assert "region_code" in cols, f"{table} missing region_code"
        assert "currency" in cols, f"{table} missing currency"
        assert "provider_code" in cols, f"{table} missing provider_code"

    # Verify backfill happened
    with engine.connect() as conn:
        for table in ("sandbox_orders", "sandbox_positions", "sandbox_funds"):
            row = conn.execute(
                text(f"SELECT region_code, currency, provider_code FROM {table}")
            ).fetchone()
            assert row is not None, f"{table} has no rows"
            assert row[0] == "india", f"{table}.region_code = {row[0]}"
            assert row[1] == "INR", f"{table}.currency = {row[1]}"
            assert row[2] == "india", f"{table}.provider_code = {row[2]}"


def test_up_migration_is_idempotent(fresh_sandbox_db):
    from upgrade.migrate_sandbox_region_columns import add_sandbox_region_columns

    assert add_sandbox_region_columns()
    # Run again — must not error or duplicate.
    assert add_sandbox_region_columns()


def test_down_migration_nulls_backfill_keeps_columns(fresh_sandbox_db):
    from upgrade.migrate_sandbox_region_columns import (
        add_sandbox_region_columns,
        revert_sandbox_region_backfill,
    )

    add_sandbox_region_columns()
    assert revert_sandbox_region_backfill()
    engine = create_engine(f"sqlite:///{fresh_sandbox_db}")
    inspector = inspect(engine)
    # Columns must still exist (D-3: no DROP).
    for table in ("sandbox_orders", "sandbox_positions", "sandbox_funds"):
        cols = {c["name"] for c in inspector.get_columns(table)}
        assert "region_code" in cols
        assert "currency" in cols
        assert "provider_code" in cols
    # But the backfill is reverted to NULL.
    with engine.connect() as conn:
        for table in ("sandbox_orders", "sandbox_positions", "sandbox_funds"):
            row = conn.execute(
                text(f"SELECT region_code, currency, provider_code FROM {table}")
            ).fetchone()
            assert row[0] is None
            assert row[1] is None
            assert row[2] is None


def test_migration_no_dropped_columns(fresh_sandbox_db):
    """Verify v4 invariant 9 — no existing column was dropped."""
    from upgrade.migrate_sandbox_region_columns import add_sandbox_region_columns

    engine = create_engine(f"sqlite:///{fresh_sandbox_db}")
    inspector = inspect(engine)
    pre_columns = {
        table: {c["name"] for c in inspector.get_columns(table)}
        for table in ("sandbox_orders", "sandbox_positions", "sandbox_funds")
    }

    add_sandbox_region_columns()

    inspector = inspect(create_engine(f"sqlite:///{fresh_sandbox_db}"))
    post_columns = {
        table: {c["name"] for c in inspector.get_columns(table)}
        for table in ("sandbox_orders", "sandbox_positions", "sandbox_funds")
    }
    for table, pre in pre_columns.items():
        # Every pre-migration column still exists post-migration.
        assert pre.issubset(post_columns[table]), (
            f"{table}: lost columns {pre - post_columns[table]}"
        )
