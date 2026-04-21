"""Phase 3b backfill: dry-run reports, --commit writes, second run is no-op."""

from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest


@pytest.fixture
def seeded_db(historify_db: Path, instruments_db: Path, reset_default_resolver):
    """Seed a DB with 3 market_data rows: two resolvable, one not."""
    from database.historify_db import get_connection, upsert_market_data
    from database.instruments_repo import (
        BrokerMapRow,
        broker_map_upsert_many,
        instruments_create,
        sync_run_start,
        venues_upsert,
    )

    # Phase 2a: seed RELIANCE + INFY on NSE so the resolver can hit them.
    venues_upsert("NSE", market_family="IN_STOCK", timezone_name="Asia/Kolkata")
    r_inst = instruments_create(
        venue_code="NSE",
        canonical_symbol="RELIANCE",
        asset_class="EQUITY",
        instrument_kind="CASH",
    )
    i_inst = instruments_create(
        venue_code="NSE",
        canonical_symbol="INFY",
        asset_class="EQUITY",
        instrument_kind="CASH",
    )
    run = sync_run_start("zerodha", "NSE")
    broker_map_upsert_many(
        "zerodha", "NSE",
        [
            BrokerMapRow("RELIANCE", "738561", r_inst.instrument_id),
            BrokerMapRow("INFY", "408065", i_inst.instrument_id),
        ],
        sync_version=run.sync_version,
    )

    # Seed 3 rows into market_data — two resolvable, one not.
    df = pd.DataFrame(
        [{"timestamp": 1700000000, "open": 100, "high": 101, "low": 99, "close": 100.5, "volume": 1000}]
    )
    upsert_market_data(df, "RELIANCE", "NSE", "1m")
    upsert_market_data(df, "INFY", "NSE", "1m")
    upsert_market_data(df, "GHOST", "NSE", "1m")

    # All rows have NULL instrument_id (flag-off writes).
    with get_connection() as conn:
        null_rows = conn.execute(
            "SELECT COUNT(*) FROM market_data WHERE instrument_id IS NULL"
        ).fetchone()[0]
        assert null_rows == 3

    return {"resolvable": 2, "missed": 1}


def test_dry_run_does_not_write(seeded_db, monkeypatch) -> None:
    """--dry-run (default) reports counts but leaves rows unchanged."""
    from database.historify_db import get_connection
    from upgrade import backfill_historify_instrument_id as bh

    stats = bh.run_backfill(
        table="market_data",
        broker_code="zerodha",
        batch_size=100,
        max_rows=None,
        commit=False,
    )
    assert stats["total"] == 3
    assert stats["resolved"] == 2
    assert stats["missed"] == 1

    with get_connection() as conn:
        still_null = conn.execute(
            "SELECT COUNT(*) FROM market_data WHERE instrument_id IS NULL"
        ).fetchone()[0]
    # Dry run: no writes.
    assert still_null == 3


def test_commit_writes_resolved_rows(seeded_db, monkeypatch) -> None:
    """--commit writes instrument_id for resolvable rows only."""
    from database.historify_db import get_connection
    from upgrade import backfill_historify_instrument_id as bh

    stats = bh.run_backfill(
        table="market_data",
        broker_code="zerodha",
        batch_size=100,
        max_rows=None,
        commit=True,
    )
    assert stats["resolved"] == 2
    assert stats["missed"] == 1

    with get_connection() as conn:
        populated = conn.execute(
            "SELECT symbol FROM market_data "
            "WHERE instrument_id IS NOT NULL "
            "ORDER BY symbol"
        ).fetchall()
        null_rows = conn.execute(
            "SELECT symbol FROM market_data WHERE instrument_id IS NULL"
        ).fetchall()

    assert [r[0] for r in populated] == ["INFY", "RELIANCE"]
    assert [r[0] for r in null_rows] == ["GHOST"]


def test_second_commit_is_noop(seeded_db, monkeypatch) -> None:
    """After a committed backfill, re-running should find zero unresolved rows."""
    from upgrade import backfill_historify_instrument_id as bh

    bh.run_backfill(
        table="market_data",
        broker_code="zerodha",
        batch_size=100,
        max_rows=None,
        commit=True,
    )
    second = bh.run_backfill(
        table="market_data",
        broker_code="zerodha",
        batch_size=100,
        max_rows=None,
        commit=True,
    )
    # Only the still-unresolved GHOST row remains visible.
    assert second["total"] == 1
    assert second["resolved"] == 0
    assert second["missed"] == 1


def test_cli_main_dry_run(seeded_db, capsys) -> None:
    """Exercise the argparse main() path to confirm DRY RUN banner and summary."""
    from upgrade import backfill_historify_instrument_id as bh

    rc = bh.main(
        ["--table", "market_data", "--broker-code", "zerodha", "--batch-size", "10"]
    )
    assert rc == 0
    out = capsys.readouterr().out
    assert "DRY RUN" in out
    assert "resolved:" in out
    assert "missed:" in out


def test_cli_main_commit(seeded_db, capsys) -> None:
    from database.historify_db import get_connection
    from upgrade import backfill_historify_instrument_id as bh

    rc = bh.main(
        [
            "--table", "market_data",
            "--broker-code", "zerodha",
            "--batch-size", "10",
            "--commit",
        ]
    )
    assert rc == 0
    out = capsys.readouterr().out
    assert "COMMITTING" in out

    with get_connection() as conn:
        populated = conn.execute(
            "SELECT COUNT(*) FROM market_data WHERE instrument_id IS NOT NULL"
        ).fetchone()[0]
    assert populated == 2


def test_max_rows_ceiling(seeded_db) -> None:
    from upgrade import backfill_historify_instrument_id as bh

    stats = bh.run_backfill(
        table="market_data",
        broker_code="zerodha",
        batch_size=100,
        max_rows=1,
        commit=False,
    )
    assert stats["total"] == 1  # ceiling respected
