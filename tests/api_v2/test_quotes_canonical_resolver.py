"""Phase 2 v3 — promoted v2 quote dispatch uses the canonical resolver only.

The promoted dispatch path resolves InstrumentRefs via
``services.instrument_resolution.resolve_instrument`` (canonical
``instruments`` table). It must never call the legacy
``database.symbol.get_token`` / ``database.token_db.get_token``
helpers.
"""

from __future__ import annotations

import sys
from unittest.mock import patch

import pytest

from services.broker_market_data_registry import (
    clear_market_data_registries_for_tests,
)


@pytest.fixture(autouse=True)
def _clean_market_data_registry():
    clear_market_data_registries_for_tests()
    yield
    clear_market_data_registries_for_tests()


def _install_fake_auth_resolver(monkeypatch, broker_code: str):
    def _fake():
        return "fake-token", broker_code, None

    monkeypatch.setattr("restx_api.v2.quotes.resolve_auth", _fake)


def _stub_caps(monkeypatch, *, broker_code: str, supported_regions, broker_type):
    from types import SimpleNamespace

    caps = SimpleNamespace(
        broker_code=broker_code,
        supported_regions=list(supported_regions),
        broker_type=broker_type,
        base_currency="USD",
    )

    def _fake(name):
        return caps if name == broker_code else None

    monkeypatch.setattr("utils.plugin_loader.get_broker_capabilities", _fake)


def test_promoted_quote_dispatch_passes_resolved_instrument_to_adapter(
    flask_app, monkeypatch, register_fake_us_adapters
):
    """The adapter must receive a ResolvedInstrument from the canonical
    resolver, not the raw symbol/exchange dict."""
    from tests.fakes.fake_us_market_data import BROKER_CODE

    monkeypatch.setenv(f"API_V2_{BROKER_CODE.upper()}", "1")
    _install_fake_auth_resolver(monkeypatch, BROKER_CODE)
    _stub_caps(
        monkeypatch,
        broker_code=BROKER_CODE,
        supported_regions=["us"],
        broker_type="US_stock",
    )

    from database import instruments_repo

    instruments_repo.venues_upsert(
        venue_code="XNAS",
        market_family="US_STOCK",
        timezone_name="America/New_York",
        country_code="US",
        base_currency="USD",
    )
    aapl = instruments_repo.instruments_create(
        venue_code="XNAS",
        canonical_symbol="AAPL",
        asset_class="EQUITY",
        instrument_kind="EQUITY",
        currency="USD",
    )

    captured = {}

    quote_adapter, _bar_adapter = register_fake_us_adapters

    original = quote_adapter.get_quote

    def _spy(instrument, account_ctx):
        captured["instrument"] = instrument
        return original(instrument, account_ctx)

    monkeypatch.setattr(quote_adapter, "get_quote", _spy)

    resp = flask_app.test_client().post(
        "/api/v2/quotes",
        json={
            "apikey": "k",
            "instruments": [{"venue_code": "XNAS", "canonical_symbol": "AAPL"}],
        },
    )
    assert resp.status_code == 200, resp.get_json()
    inst = captured["instrument"]
    assert str(inst.instrument_id) == str(aapl.instrument_id)
    assert inst.venue_code == "XNAS"
    assert inst.canonical_symbol == "AAPL"


def test_promoted_quote_dispatch_does_not_load_legacy_symbol_module(
    flask_app, monkeypatch, register_fake_us_adapters
):
    """After a promoted dispatch run, ``database.symbol.get_token``
    must not have been imported into ``sys.modules``.

    Because conftest may have imported these modules earlier in the
    test run for other reasons, we instead patch them and assert they
    were not called.
    """
    from tests.fakes.fake_us_market_data import BROKER_CODE

    monkeypatch.setenv(f"API_V2_{BROKER_CODE.upper()}", "1")
    _install_fake_auth_resolver(monkeypatch, BROKER_CODE)
    _stub_caps(
        monkeypatch,
        broker_code=BROKER_CODE,
        supported_regions=["us"],
        broker_type="US_stock",
    )

    from database import instruments_repo

    instruments_repo.venues_upsert(
        venue_code="XNAS",
        market_family="US_STOCK",
        timezone_name="America/New_York",
        country_code="US",
        base_currency="USD",
    )
    instruments_repo.instruments_create(
        venue_code="XNAS",
        canonical_symbol="AAPL",
        asset_class="EQUITY",
        instrument_kind="EQUITY",
        currency="USD",
    )

    with patch("database.token_db.get_token") as legacy_get_token, patch(
        "services.quotes_service.get_quotes_with_auth"
    ) as legacy_quotes:
        resp = flask_app.test_client().post(
            "/api/v2/quotes",
            json={
                "apikey": "k",
                "instruments": [{"venue_code": "XNAS", "canonical_symbol": "AAPL"}],
            },
        )
    assert resp.status_code == 200, resp.get_json()
    legacy_get_token.assert_not_called()
    legacy_quotes.assert_not_called()
