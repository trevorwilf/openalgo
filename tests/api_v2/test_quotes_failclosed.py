"""Phase 2 v3 — fail-closed dispatch for /api/v2/quotes (ADR 0018).

Mirrors the v2 orders fail-closed contract for the market-data
surface. The legacy ``services.quotes_service`` is unreachable from
non-India non-crypto brokers; instead these brokers either dispatch
through a registered :class:`BrokerQuoteAdapter` or fail with
``promoted_capability_unavailable`` / ``promoted_lane_required_for_non_india_broker``.

India and crypto brokers continue to fall back to the legacy lane
for parity.
"""

from __future__ import annotations

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
        base_currency="USD" if broker_type != "IN_stock" else "INR",
    )

    def _fake(name):
        return caps if name == broker_code else None

    monkeypatch.setattr("utils.plugin_loader.get_broker_capabilities", _fake)


def _body(refs=None):
    return {
        "apikey": "k",
        "instruments": refs or [{"venue_code": "XNAS", "canonical_symbol": "AAPL"}],
    }


# ---------------------------------------------------------------------------
# Non-India broker, flag ON, no adapter → 503 quote_adapter_not_registered
# ---------------------------------------------------------------------------


def test_non_india_flag_on_no_adapter_returns_503(flask_app, monkeypatch):
    monkeypatch.setenv("API_V2_FAKE_US", "1")
    _install_fake_auth_resolver(monkeypatch, "fake_us")
    _stub_caps(
        monkeypatch,
        broker_code="fake_us",
        supported_regions=["us"],
        broker_type="US_stock",
    )

    with patch("services.quotes_service.get_quotes_with_auth") as legacy:
        resp = flask_app.test_client().post("/api/v2/quotes", json=_body())
    assert resp.status_code == 503, resp.get_json()
    body = resp.get_json()
    assert body["error"]["code"] == "promoted_capability_unavailable"
    assert body["error"]["details"]["sub_code"] == "quote_adapter_not_registered"
    legacy.assert_not_called()


# ---------------------------------------------------------------------------
# Non-India broker, flag ON, adapter registered, instrument resolves
# → normalized quote, no legacy call
# ---------------------------------------------------------------------------


def test_non_india_flag_on_adapter_registered_returns_quote(
    flask_app, monkeypatch, register_fake_us_adapters
):
    from tests.fakes.fake_us_market_data import BROKER_CODE

    monkeypatch.setenv(f"API_V2_{BROKER_CODE.upper()}", "1")
    _install_fake_auth_resolver(monkeypatch, BROKER_CODE)
    _stub_caps(
        monkeypatch,
        broker_code=BROKER_CODE,
        supported_regions=["us"],
        broker_type="US_stock",
    )

    # Insert an instrument so the resolver hits the canonical path.
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

    with patch("services.quotes_service.get_quotes_with_auth") as legacy:
        resp = flask_app.test_client().post("/api/v2/quotes", json=_body())
    assert resp.status_code == 200, resp.get_json()
    body = resp.get_json()
    assert body["data"][0]["instrument"]["canonical_symbol"] == "AAPL"
    assert body["data"][0]["instrument"]["instrument_id"] == str(aapl.instrument_id)
    legacy.assert_not_called()


# ---------------------------------------------------------------------------
# Non-India broker, flag ON, adapter registered, instrument NOT resolvable
# → per-ref instrument_not_resolvable error
# ---------------------------------------------------------------------------


def test_non_india_flag_on_adapter_registered_unresolvable_ref(
    flask_app, monkeypatch, register_fake_us_adapters
):
    from tests.fakes.fake_us_market_data import BROKER_CODE

    monkeypatch.setenv(f"API_V2_{BROKER_CODE.upper()}", "1")
    _install_fake_auth_resolver(monkeypatch, BROKER_CODE)
    _stub_caps(
        monkeypatch,
        broker_code=BROKER_CODE,
        supported_regions=["us"],
        broker_type="US_stock",
    )

    with patch("services.quotes_service.get_quotes_with_auth") as legacy:
        resp = flask_app.test_client().post(
            "/api/v2/quotes",
            json=_body([{"venue_code": "XNAS", "canonical_symbol": "DOES_NOT_EXIST"}]),
        )
    assert resp.status_code == 200, resp.get_json()
    body = resp.get_json()
    assert body["data"][0]["error"]["code"] == "instrument_not_resolvable"
    legacy.assert_not_called()


# ---------------------------------------------------------------------------
# Non-India broker, flag OFF → 503 promoted_lane_required_for_non_india_broker
# ---------------------------------------------------------------------------


def test_non_india_flag_off_returns_503_promoted_lane_required(
    flask_app, monkeypatch
):
    monkeypatch.delenv("API_V2_FAKE_US", raising=False)
    _install_fake_auth_resolver(monkeypatch, "fake_us")
    _stub_caps(
        monkeypatch,
        broker_code="fake_us",
        supported_regions=["us"],
        broker_type="US_stock",
    )

    with patch("services.quotes_service.get_quotes_with_auth") as legacy:
        resp = flask_app.test_client().post("/api/v2/quotes", json=_body())
    assert resp.status_code == 503, resp.get_json()
    body = resp.get_json()
    assert body["error"]["code"] == "promoted_lane_required_for_non_india_broker"
    legacy.assert_not_called()


# ---------------------------------------------------------------------------
# India broker, flag OFF → legacy fallback works (parity)
# ---------------------------------------------------------------------------


def test_india_flag_off_legacy_path_works(flask_app, monkeypatch):
    monkeypatch.delenv("API_V2_ZERODHA", raising=False)
    _install_fake_auth_resolver(monkeypatch, "zerodha")
    _stub_caps(
        monkeypatch,
        broker_code="zerodha",
        supported_regions=["india"],
        broker_type="IN_stock",
    )

    with patch("services.quotes_service.get_quotes_with_auth") as legacy:
        legacy.return_value = (True, {"data": {"ltp": 100.0}}, 200)
        resp = flask_app.test_client().post(
            "/api/v2/quotes",
            json=_body([{"venue_code": "NSE", "canonical_symbol": "INFY"}]),
        )
    assert resp.status_code == 200, resp.get_json()
    legacy.assert_called_once()


# ---------------------------------------------------------------------------
# Crypto broker, flag OFF → legacy fallback works (parity)
# ---------------------------------------------------------------------------


def test_crypto_flag_off_legacy_path_works(flask_app, monkeypatch):
    monkeypatch.delenv("API_V2_DELTAEXCHANGE", raising=False)
    _install_fake_auth_resolver(monkeypatch, "deltaexchange")
    _stub_caps(
        monkeypatch,
        broker_code="deltaexchange",
        supported_regions=["india"],
        broker_type="crypto",
    )

    with patch("services.quotes_service.get_quotes_with_auth") as legacy:
        legacy.return_value = (True, {"data": {"ltp": 50000.0}}, 200)
        resp = flask_app.test_client().post(
            "/api/v2/quotes",
            json=_body([{"venue_code": "CRYPTO", "canonical_symbol": "BTC-USD"}]),
        )
    assert resp.status_code == 200, resp.get_json()
    legacy.assert_called_once()
