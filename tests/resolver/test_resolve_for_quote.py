"""`resolve_for_quote(symbol, exchange, broker_code)` convenience wrapper."""

from __future__ import annotations

from database.instruments_repo import (
    BrokerMapRow,
    broker_map_upsert_many,
    instruments_create,
    sync_run_start,
    venues_upsert,
)
from services.instrument_resolver import InstrumentResolver


def test_resolve_for_quote_hits(fresh_db) -> None:
    venues_upsert("NSE", market_family="IN_STOCK", timezone_name="Asia/Kolkata")
    inst = instruments_create(
        venue_code="NSE",
        canonical_symbol="AXISBANK",
        asset_class="EQUITY",
        instrument_kind="CASH",
    )
    r = sync_run_start("zerodha", "NSE")
    broker_map_upsert_many(
        "zerodha",
        "NSE",
        [BrokerMapRow("AXISBANK", "1510401", inst.instrument_id)],
        sync_version=r.sync_version,
    )

    resolver = InstrumentResolver()
    result = resolver.resolve_for_quote(
        symbol="AXISBANK", exchange="NSE", broker_code="zerodha"
    )
    assert result.instrument_id == inst.instrument_id
    assert result.external_token == "1510401"


def test_resolve_for_quote_legacy_fallback(fresh_db) -> None:
    def legacy_get_token(symbol: str, exchange: str):
        return 98765 if symbol == "SBIN" and exchange == "NSE" else None

    resolver = InstrumentResolver(legacy_token_lookup=legacy_get_token)
    result = resolver.resolve_for_quote(
        symbol="SBIN", exchange="NSE", broker_code="zerodha"
    )
    assert result.legacy_fallback is True
    assert result.external_token == "98765"
