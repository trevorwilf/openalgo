"""Phase 3 v3 / ADR 0019 — promoted resolver never touches legacy
token DB modules for non-India brokers.

The promoted-lane resolver (``services.instrument_resolution``) was
designed to import only from ``database.instruments_repo``. This test
proves the contract by patching every legacy entry point and asserting
none of them are called when resolving for a non-India broker.

For India brokers the resolver is *not* expected to call legacy
modules either — the migration to canonical-resolver-by-default for
India is gated behind a future operator-controlled phase. This test
locks the contract for the non-India side today.
"""

from __future__ import annotations

from unittest.mock import patch

import pytest


def _seed_us_instrument(broker_code: str = "fake_us"):
    from database import instruments_repo

    instruments_repo.venues_upsert(
        venue_code="XNAS",
        market_family="US_STOCK",
        timezone_name="America/New_York",
        country_code="US",
        base_currency="USD",
    )
    return instruments_repo.instruments_create(
        venue_code="XNAS",
        canonical_symbol="AAPL",
        asset_class="EQUITY",
        instrument_kind="EQUITY",
        currency="USD",
    )


def test_resolver_for_non_india_broker_does_not_call_legacy_token_db(fresh_db):
    """Resolve a venue_symbol ref for a non-India broker. Patch every
    legacy token-DB function. Assert none of them is called.
    """
    from domain.instrument_ref import InstrumentRef
    from services.instrument_resolution import resolve_instrument

    aapl = _seed_us_instrument()
    ref = InstrumentRef(venue_code="XNAS", canonical_symbol="AAPL")

    with patch("database.token_db.get_token") as get_token, patch(
        "database.token_db.get_brexchange"
    ) as get_brex, patch("database.token_db_enhanced.fno_search_symbols") as fno:
        resolved = resolve_instrument(ref, broker_code="fake_us")
    assert resolved is not None
    assert str(resolved.instrument_id) == str(aapl.instrument_id)
    get_token.assert_not_called()
    get_brex.assert_not_called()
    fno.assert_not_called()


def test_resolver_unresolvable_for_non_india_broker_returns_none(fresh_db):
    """A non-India broker requesting a symbol that isn't in the
    canonical universe returns None — no legacy fallback at all."""
    from domain.instrument_ref import InstrumentRef
    from services.instrument_resolution import resolve_instrument

    ref = InstrumentRef(venue_code="XNAS", canonical_symbol="DOES_NOT_EXIST")

    with patch("database.token_db.get_token") as get_token:
        resolved = resolve_instrument(ref, broker_code="fake_us")
    assert resolved is None
    get_token.assert_not_called()


def test_resolver_external_ref_for_non_india_uses_broker_map_only(fresh_db):
    """An external (broker_token) ref for a non-India broker uses the
    canonical broker_instrument_map; no legacy token DB lookup."""
    from domain.instrument_ref import InstrumentRef
    from database import instruments_repo
    from services.instrument_resolution import resolve_instrument

    aapl = _seed_us_instrument()
    instruments_repo.broker_map_upsert_many(
        broker_code="fake_us",
        venue_code="XNAS",
        rows=[
            instruments_repo.BrokerMapRow(
                external_symbol="AAPL",
                external_token="ALPACA-AAPL",
                instrument_id=aapl.instrument_id,
            )
        ],
        sync_version=1,
    )
    ref = InstrumentRef(
        venue_code="XNAS",
        identifier_type="BROKER_TOKEN",
        identifier_value="ALPACA-AAPL",
        broker_code="fake_us",
    )
    with patch("database.token_db.get_token") as get_token:
        resolved = resolve_instrument(ref, broker_code="fake_us")
    assert resolved is not None
    assert resolved.broker_native_token == "ALPACA-AAPL"
    get_token.assert_not_called()
