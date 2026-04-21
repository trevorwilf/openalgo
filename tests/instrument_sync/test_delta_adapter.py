"""Delta Exchange adapter + runner end-to-end against fixture JSON."""

from __future__ import annotations

from pathlib import Path

from database.instruments_repo import (
    broker_map_lookup_by_symbol,
    identifier_resolve,
    instruments_get_by_venue_symbol,
    sync_run_latest,
    venues_list,
)
from services.instrument_sync_adapters.delta_adapter import DeltaAdapter
from services.instrument_sync_service import InstrumentSyncRunner


def test_delta_full_run(fresh_db, delta_fixture: Path) -> None:
    adapter = DeltaAdapter(json_path=delta_fixture)
    result = InstrumentSyncRunner().run(adapter)

    # 8 products in fixture; one unsupported product_type is filtered.
    assert result.status == "success"
    assert result.instrument_count == 7
    assert result.new_count == 7

    venues = {v.venue_code for v in venues_list()}
    assert "DELTA_EXCHANGE" in venues

    spot = instruments_get_by_venue_symbol("DELTA_EXCHANGE", "BTC_USDT")
    assert spot is not None
    assert spot.asset_class == "SPOT"

    # Perpetual
    from database.instruments_repo import Instrument, session_scope
    from sqlalchemy import select

    with session_scope() as s:
        perp = s.scalar(
            select(Instrument).where(
                Instrument.venue_code == "DELTA_EXCHANGE",
                Instrument.canonical_symbol == "BTCUSD",
            )
        )
    assert perp is not None
    assert perp.asset_class == "PERPETUAL"
    assert perp.instrument_kind == "DERIVATIVE"

    # Option carries strike + option_right + expiry
    with session_scope() as s:
        call = s.scalar(
            select(Instrument).where(
                Instrument.venue_code == "DELTA_EXCHANGE",
                Instrument.canonical_symbol == "C-BTC-50000-280225",
            )
        )
    assert call is not None
    assert call.option_right == "CALL"
    assert call.strike is not None
    assert call.expiration_at is not None

    # Broker map reachable by both symbol and product_id
    sym = broker_map_lookup_by_symbol("deltaexchange", "DELTA_EXCHANGE", "BTC_USDT")
    assert sym is not None

    latest = sync_run_latest("deltaexchange")
    assert latest is not None
    assert latest.status == "success"


def test_delta_unknown_product_type_skipped(fresh_db, delta_fixture: Path) -> None:
    result = InstrumentSyncRunner().run(DeltaAdapter(json_path=delta_fixture))
    assert result.instrument_count == 7  # 8 - 1 unsupported


def test_delta_identifiers(fresh_db, delta_fixture: Path) -> None:
    InstrumentSyncRunner().run(DeltaAdapter(json_path=delta_fixture))
    matches = identifier_resolve(
        "BROKER_TOKEN", "20001",
        broker_code="deltaexchange", venue_code="DELTA_EXCHANGE",
    )
    assert len(matches) == 1
