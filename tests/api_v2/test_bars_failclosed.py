"""Phase 2 v3 — fail-closed dispatch for /api/v2/bars (ADR 0018).

Mirror of :mod:`tests.api_v2.test_quotes_failclosed` for the bar
adapter. The legacy ``services.history_service`` is unreachable from
non-India non-crypto brokers; instead these brokers either dispatch
through a registered :class:`BrokerBarAdapter` or fail with
``promoted_capability_unavailable`` /
``promoted_lane_required_for_non_india_broker``.
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

    monkeypatch.setattr("restx_api.v2.bars.resolve_auth", _fake)


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


def _body(ref=None):
    return {
        "apikey": "k",
        "instrument": ref or {"venue_code": "XNAS", "canonical_symbol": "AAPL"},
        "interval": "1m",
        "start": "2026-04-23T13:30:00Z",
        "end": "2026-04-23T20:00:00Z",
    }


def test_non_india_flag_on_no_adapter_returns_503(flask_app, monkeypatch):
    monkeypatch.setenv("API_V2_FAKE_US", "1")
    _install_fake_auth_resolver(monkeypatch, "fake_us")
    _stub_caps(
        monkeypatch,
        broker_code="fake_us",
        supported_regions=["us"],
        broker_type="US_stock",
    )

    with patch("services.history_service.get_history_with_auth") as legacy:
        resp = flask_app.test_client().post("/api/v2/bars", json=_body())
    assert resp.status_code == 503, resp.get_json()
    body = resp.get_json()
    assert body["error"]["code"] == "promoted_capability_unavailable"
    assert body["error"]["details"]["sub_code"] == "bar_adapter_not_registered"
    legacy.assert_not_called()


def test_non_india_flag_on_adapter_registered_returns_bars(
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

    with patch("services.history_service.get_history_with_auth") as legacy:
        resp = flask_app.test_client().post("/api/v2/bars", json=_body())
    assert resp.status_code == 200, resp.get_json()
    body = resp.get_json()
    assert body["data"]["instrument"]["instrument_id"] == str(aapl.instrument_id)
    assert len(body["data"]["bars"]) == 3
    legacy.assert_not_called()


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

    with patch("services.history_service.get_history_with_auth") as legacy:
        resp = flask_app.test_client().post(
            "/api/v2/bars",
            json=_body({"venue_code": "XNAS", "canonical_symbol": "DOES_NOT_EXIST"}),
        )
    assert resp.status_code == 422, resp.get_json()
    assert resp.get_json()["error"]["code"] == "instrument_not_resolvable"
    legacy.assert_not_called()


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

    with patch("services.history_service.get_history_with_auth") as legacy:
        resp = flask_app.test_client().post("/api/v2/bars", json=_body())
    assert resp.status_code == 503, resp.get_json()
    assert resp.get_json()["error"]["code"] == "promoted_lane_required_for_non_india_broker"
    legacy.assert_not_called()


def test_india_flag_off_legacy_path_works(flask_app, monkeypatch):
    monkeypatch.delenv("API_V2_ZERODHA", raising=False)
    _install_fake_auth_resolver(monkeypatch, "zerodha")
    _stub_caps(
        monkeypatch,
        broker_code="zerodha",
        supported_regions=["india"],
        broker_type="IN_stock",
    )

    with patch("services.history_service.get_history_with_auth") as legacy:
        legacy.return_value = (True, {"data": [{"ts": 1, "open": 100}]}, 200)
        resp = flask_app.test_client().post(
            "/api/v2/bars",
            json=_body({"venue_code": "NSE", "canonical_symbol": "INFY"}),
        )
    assert resp.status_code == 200
    legacy.assert_called_once()


def test_crypto_flag_off_legacy_path_works(flask_app, monkeypatch):
    monkeypatch.delenv("API_V2_DELTAEXCHANGE", raising=False)
    _install_fake_auth_resolver(monkeypatch, "deltaexchange")
    _stub_caps(
        monkeypatch,
        broker_code="deltaexchange",
        supported_regions=["india"],
        broker_type="crypto",
    )

    with patch("services.history_service.get_history_with_auth") as legacy:
        legacy.return_value = (True, {"data": [{"ts": 1, "open": 50000}]}, 200)
        resp = flask_app.test_client().post(
            "/api/v2/bars",
            json=_body({"venue_code": "CRYPTO", "canonical_symbol": "BTC-USD"}),
        )
    assert resp.status_code == 200
    legacy.assert_called_once()
