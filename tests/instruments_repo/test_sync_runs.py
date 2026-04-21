"""Sync-run lifecycle + version progression."""

from __future__ import annotations

import uuid

from database.instruments_repo import (
    sync_run_complete,
    sync_run_fail,
    sync_run_latest,
    sync_run_start,
    venues_upsert,
)


def test_start_assigns_incremented_version(fresh_db) -> None:
    venues_upsert("NSE", market_family="IN_STOCK", timezone_name="Asia/Kolkata")
    r1 = sync_run_start("zerodha", "NSE", source="kite CSV")
    r2 = sync_run_start("zerodha", "NSE")
    r3 = sync_run_start("zerodha", "NSE")
    assert r1.sync_version == 1
    assert r2.sync_version == 2
    assert r3.sync_version == 3
    assert r1.status == "running"
    assert r1.source == "kite CSV"


def test_version_is_per_broker_venue(fresh_db) -> None:
    venues_upsert("NSE", market_family="IN_STOCK", timezone_name="Asia/Kolkata")
    venues_upsert("BSE", market_family="IN_STOCK", timezone_name="Asia/Kolkata")
    zerodha_nse = sync_run_start("zerodha", "NSE")
    zerodha_bse = sync_run_start("zerodha", "BSE")
    dhan_nse = sync_run_start("dhan", "NSE")
    # Each (broker, venue) pair has its own counter starting at 1.
    assert zerodha_nse.sync_version == 1
    assert zerodha_bse.sync_version == 1
    assert dhan_nse.sync_version == 1


def test_complete_success_marks_and_counts(fresh_db) -> None:
    venues_upsert("NSE", market_family="IN_STOCK", timezone_name="Asia/Kolkata")
    r = sync_run_start("zerodha", "NSE")
    completed = sync_run_complete(r.sync_id, instrument_count=1234, checksum="abc123")
    assert completed is not None
    assert completed.status == "success"
    assert completed.instrument_count == 1234
    assert completed.checksum == "abc123"
    assert completed.completed_at is not None


def test_fail_records_error(fresh_db) -> None:
    venues_upsert("NSE", market_family="IN_STOCK", timezone_name="Asia/Kolkata")
    r = sync_run_start("zerodha", "NSE")
    failed = sync_run_fail(r.sync_id, "HTTP 500 from broker CSV endpoint")
    assert failed is not None
    assert failed.status == "failed"
    assert failed.error == "HTTP 500 from broker CSV endpoint"
    assert failed.completed_at is not None


def test_complete_missing_run_returns_none(fresh_db) -> None:
    assert sync_run_complete(uuid.uuid4(), instrument_count=0) is None


def test_fail_missing_run_returns_none(fresh_db) -> None:
    assert sync_run_fail(uuid.uuid4(), "nope") is None


def test_latest_returns_highest_version(fresh_db) -> None:
    venues_upsert("NSE", market_family="IN_STOCK", timezone_name="Asia/Kolkata")
    sync_run_start("zerodha", "NSE")
    sync_run_start("zerodha", "NSE")
    r3 = sync_run_start("zerodha", "NSE")
    latest = sync_run_latest("zerodha", "NSE")
    assert latest is not None
    assert latest.sync_version == 3
    assert latest.sync_id == r3.sync_id


def test_latest_without_venue_matches_any(fresh_db) -> None:
    venues_upsert("NSE", market_family="IN_STOCK", timezone_name="Asia/Kolkata")
    venues_upsert("BSE", market_family="IN_STOCK", timezone_name="Asia/Kolkata")
    sync_run_start("zerodha", "NSE")
    sync_run_start("zerodha", "BSE")
    latest = sync_run_latest("zerodha")  # any venue
    assert latest is not None
    assert latest.broker_code == "zerodha"


def test_latest_no_runs_returns_none(fresh_db) -> None:
    assert sync_run_latest("unknown_broker") is None
