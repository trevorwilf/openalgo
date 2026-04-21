"""Two-broker coexistence: syncing Zerodha then Delta leaves both row
sets visible. This is the property the refactor is fundamentally
about — today's `delete_symtoken_table()` pattern makes it impossible.
"""

from __future__ import annotations

from pathlib import Path

from database.instruments_repo import (
    broker_map_lookup_by_symbol,
    instruments_search,
    sync_run_latest,
)
from services.instrument_sync_adapters.delta_adapter import DeltaAdapter
from services.instrument_sync_adapters.zerodha_adapter import ZerodhaAdapter
from services.instrument_sync_service import InstrumentSyncRunner


def test_two_brokers_coexist(
    fresh_db, zerodha_fixture: Path, delta_fixture: Path
) -> None:
    # First sync — Zerodha
    z_result = InstrumentSyncRunner().run(ZerodhaAdapter(csv_path=zerodha_fixture))
    # Then sync — Delta (crypto, completely different venue)
    d_result = InstrumentSyncRunner().run(DeltaAdapter(json_path=delta_fixture))

    # 1. Both broker-map rows exist, both reachable by their own broker_code.
    assert (
        broker_map_lookup_by_symbol("zerodha", "NSE", "RELIANCE") is not None
    )
    assert (
        broker_map_lookup_by_symbol("deltaexchange", "DELTA_EXCHANGE", "BTC_USDT")
        is not None
    )

    # 2. Syncing Delta did NOT retire any Zerodha broker-map rows —
    #    soft-prune is per-(broker, venue).
    assert d_result.retired_count == 0

    # 3. Zerodha's latest sync is still complete and independent.
    z_latest = sync_run_latest("zerodha")
    assert z_latest is not None
    assert z_latest.status == "success"
    assert z_latest.sync_version == z_result.sync_version

    d_latest = sync_run_latest("deltaexchange")
    assert d_latest is not None
    assert d_latest.status == "success"

    # 4. instruments_search finds rows from both brokers (search is
    #    broker-agnostic; it asks about the canonical universe).
    nse_rows = instruments_search(venue_code="NSE")
    delta_rows = instruments_search(venue_code="DELTA_EXCHANGE")
    assert len(nse_rows) >= 3  # RELIANCE, INFY, TCS from the fixture
    assert len(delta_rows) >= 2  # BTC_USDT, ETH_USDT, etc.


def test_sync_version_isolated_per_broker(
    fresh_db, zerodha_fixture: Path, delta_fixture: Path
) -> None:
    """Two separate sync runs must each get sync_version=1 — the counter
    is per-(broker, venue)."""
    z = InstrumentSyncRunner().run(ZerodhaAdapter(csv_path=zerodha_fixture))
    d = InstrumentSyncRunner().run(DeltaAdapter(json_path=delta_fixture))
    assert z.sync_version == 1
    assert d.sync_version == 1
