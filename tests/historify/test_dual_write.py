"""Phase 3b dual-write: instrument_id populated when flag is on AND
broker has a populated resolver; NULL otherwise.
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest


@pytest.fixture
def reliance_instrument(instruments_db: Path):
    """Seed a RELIANCE instrument in the Phase 2a tables so the resolver hits."""
    from database.instruments_repo import (
        BrokerMapRow,
        broker_map_upsert_many,
        instruments_create,
        sync_run_start,
        venues_upsert,
    )

    venues_upsert("NSE", market_family="IN_STOCK", timezone_name="Asia/Kolkata")
    inst = instruments_create(
        venue_code="NSE",
        canonical_symbol="RELIANCE",
        asset_class="EQUITY",
        instrument_kind="CASH",
    )
    r = sync_run_start("zerodha", "NSE")
    broker_map_upsert_many(
        "zerodha", "NSE",
        [BrokerMapRow("RELIANCE", "738561", inst.instrument_id)],
        sync_version=r.sync_version,
    )
    return inst


def _sample_df() -> pd.DataFrame:
    return pd.DataFrame(
        [{"timestamp": 1700000000, "open": 100, "high": 101, "low": 99, "close": 100.5, "volume": 1000}]
    )


def _market_data_instrument_id() -> str | None:
    from database.historify_db import get_connection

    with get_connection() as conn:
        rows = conn.execute(
            "SELECT instrument_id FROM market_data LIMIT 1"
        ).fetchall()
    return rows[0][0] if rows else None


def test_flag_off_writes_null_instrument_id(
    historify_db: Path, instruments_db: Path, monkeypatch, reliance_instrument
) -> None:
    monkeypatch.delenv("HISTORIFY_INSTRUMENT_ID_V2", raising=False)
    from database.historify_db import upsert_market_data

    upsert_market_data(_sample_df(), "RELIANCE", "NSE", "1m")
    assert _market_data_instrument_id() is None


def test_flag_on_writes_resolved_instrument_id(
    historify_db: Path, instruments_db: Path, monkeypatch,
    reset_default_resolver, reliance_instrument,
) -> None:
    monkeypatch.setenv("HISTORIFY_INSTRUMENT_ID_V2", "1")
    monkeypatch.setenv("BROKER_NAME", "zerodha")

    from services.historify_service import _maybe_resolve_instrument_id
    from database.historify_db import upsert_market_data

    resolved = _maybe_resolve_instrument_id("RELIANCE", "NSE")
    assert resolved == str(reliance_instrument.instrument_id)

    upsert_market_data(_sample_df(), "RELIANCE", "NSE", "1m", instrument_id=resolved)
    assert _market_data_instrument_id() == str(reliance_instrument.instrument_id)


def test_flag_on_unresolvable_writes_null(
    historify_db: Path, instruments_db: Path, monkeypatch, reset_default_resolver
) -> None:
    """Resolver misses (no instrument, no legacy fallback) → None → NULL."""
    monkeypatch.setenv("HISTORIFY_INSTRUMENT_ID_V2", "1")
    monkeypatch.setenv("BROKER_NAME", "zerodha")

    from services.historify_service import _maybe_resolve_instrument_id
    from database.historify_db import upsert_market_data

    resolved = _maybe_resolve_instrument_id("GHOST_SYMBOL", "NSE")
    assert resolved is None

    upsert_market_data(
        _sample_df(), "GHOST_SYMBOL", "NSE", "1m", instrument_id=resolved
    )
    assert _market_data_instrument_id() is None


def test_flag_on_no_broker_context_writes_null(
    historify_db: Path, instruments_db: Path, monkeypatch
) -> None:
    """Flag on but no BROKER_NAME and no Flask session → helper returns None."""
    monkeypatch.setenv("HISTORIFY_INSTRUMENT_ID_V2", "1")
    monkeypatch.delenv("BROKER_NAME", raising=False)

    from services.historify_service import _maybe_resolve_instrument_id

    assert _maybe_resolve_instrument_id("RELIANCE", "NSE") is None


def test_existing_instrument_id_not_clobbered_by_legacy_writer(
    historify_db: Path, instruments_db: Path, monkeypatch,
    reset_default_resolver, reliance_instrument,
) -> None:
    """Scenario: flag-on writer sets instrument_id; then flag-off writer
    re-upserts (e.g. a second download for the same bar). The upsert's
    ON CONFLICT must NOT overwrite the existing instrument_id with NULL.
    """
    from database.historify_db import upsert_market_data

    # First write with instrument_id set
    iid = str(reliance_instrument.instrument_id)
    upsert_market_data(_sample_df(), "RELIANCE", "NSE", "1m", instrument_id=iid)
    assert _market_data_instrument_id() == iid

    # Second write without instrument_id (legacy-mode writer)
    upsert_market_data(_sample_df(), "RELIANCE", "NSE", "1m", instrument_id=None)
    # The COALESCE(EXCLUDED.instrument_id, market_data.instrument_id) preserves it.
    assert _market_data_instrument_id() == iid


def test_watchlist_dual_write(
    historify_db: Path, instruments_db: Path, monkeypatch,
    reset_default_resolver, reliance_instrument,
) -> None:
    monkeypatch.setenv("HISTORIFY_INSTRUMENT_ID_V2", "1")
    monkeypatch.setenv("BROKER_NAME", "zerodha")

    from database.historify_db import add_to_watchlist, get_connection
    from services.historify_service import _maybe_resolve_instrument_id

    iid = _maybe_resolve_instrument_id("RELIANCE", "NSE")
    success, _ = add_to_watchlist("RELIANCE", "NSE", instrument_id=iid)
    assert success is True

    with get_connection() as conn:
        rows = conn.execute(
            "SELECT instrument_id FROM watchlist WHERE symbol = 'RELIANCE'"
        ).fetchall()
    assert rows[0][0] == str(reliance_instrument.instrument_id)
