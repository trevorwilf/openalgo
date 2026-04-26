"""Phase 6 v3 (ADR 0022) — /api/v2/orders/combo dispatch tests."""

from __future__ import annotations

from decimal import Decimal

import pytest

from services.broker_translator_registry import clear_registry_for_tests


@pytest.fixture(autouse=True)
def _clean_registry():
    clear_registry_for_tests()
    yield
    clear_registry_for_tests()


def _install_fake_auth_resolver(monkeypatch, broker_code: str):
    def _fake():
        return "fake-token", broker_code, None

    monkeypatch.setattr("restx_api.v2.orders_combo.resolve_auth", _fake)


def _stub_caps(monkeypatch, *, broker_code: str, supports_combo_types):
    from types import SimpleNamespace

    from domain.enums import ComboType

    caps = SimpleNamespace(
        broker_code=broker_code,
        supported_regions=["us"],
        broker_type="US_stock",
        base_currency=None,
        supports_combo_types=[ComboType(c) for c in supports_combo_types],
    )

    def _fake(name):
        return caps if name == broker_code else None

    monkeypatch.setattr("utils.plugin_loader.get_broker_capabilities", _fake)


def _seed_aapl_msft(broker_code: str):
    from database import instruments_repo

    instruments_repo.venues_upsert(
        venue_code="XNAS",
        market_family="US_STOCK",
        timezone_name="America/New_York",
        country_code="US",
        base_currency="USD",
    )
    aapl = instruments_repo.instruments_create(
        venue_code="XNAS", canonical_symbol="AAPL",
        asset_class="EQUITY", instrument_kind="EQUITY", currency="USD",
    )
    msft = instruments_repo.instruments_create(
        venue_code="XNAS", canonical_symbol="MSFT",
        asset_class="EQUITY", instrument_kind="EQUITY", currency="USD",
    )
    return aapl, msft


def _otoco_body() -> dict:
    return {
        "apikey": "k",
        "combo_type": "OTOCO",
        "time_in_force": "DAY",
        "session": "REGULAR",
        "link_id": "TEST-LINK-1",
        "legs": [
            {
                "instrument_ref": {"venue_code": "XNAS", "canonical_symbol": "AAPL"},
                "side": "BUY",
                "quantity": "1",
                "quantity_unit": "WHOLE",
                "order_type": "LIMIT",
                "price": "150.00",
            },
            {
                "instrument_ref": {"venue_code": "XNAS", "canonical_symbol": "AAPL"},
                "side": "SELL",
                "quantity": "1",
                "quantity_unit": "WHOLE",
                "order_type": "LIMIT",
                "price": "155.00",
            },
            {
                "instrument_ref": {"venue_code": "XNAS", "canonical_symbol": "AAPL"},
                "side": "SELL",
                "quantity": "1",
                "quantity_unit": "WHOLE",
                "order_type": "STOP",
                "trigger_price": "145.00",
            },
        ],
    }


def test_combo_no_translator_returns_503(flask_app, monkeypatch):
    monkeypatch.setenv("API_V2__MOCK_SCHWAB_LIKE", "1")
    _install_fake_auth_resolver(monkeypatch, "_mock_schwab_like")
    _stub_caps(
        monkeypatch,
        broker_code="_mock_schwab_like",
        supports_combo_types=["OTOCO"],
    )

    resp = flask_app.test_client().post("/api/v2/orders/combo", json=_otoco_body())
    assert resp.status_code == 503, resp.get_json()
    assert resp.get_json()["error"]["code"] == "translator_not_registered"


def test_combo_unsupported_combo_type_returns_422(flask_app, monkeypatch):
    monkeypatch.setenv("API_V2__MOCK_SCHWAB_LIKE", "1")
    _install_fake_auth_resolver(monkeypatch, "_mock_schwab_like")
    _stub_caps(
        monkeypatch,
        broker_code="_mock_schwab_like",
        supports_combo_types=["OCO"],  # OTOCO not supported
    )
    from broker._mock_schwab_like.api.order_api import (
        install_mock_schwab_like_translator,
    )

    install_mock_schwab_like_translator()
    _seed_aapl_msft("_mock_schwab_like")

    resp = flask_app.test_client().post("/api/v2/orders/combo", json=_otoco_body())
    assert resp.status_code == 422, resp.get_json()
    body = resp.get_json()
    assert body["error"]["code"] == "unsupported_capability"
    assert body["error"]["details"]["capability_name"] == "combo_type"


def test_combo_otoco_dispatch_to_schwab_like(flask_app, monkeypatch):
    monkeypatch.setenv("API_V2__MOCK_SCHWAB_LIKE", "1")
    _install_fake_auth_resolver(monkeypatch, "_mock_schwab_like")
    _stub_caps(
        monkeypatch,
        broker_code="_mock_schwab_like",
        supports_combo_types=["OTOCO", "MULTILEG_OPTIONS"],
    )
    from broker._mock_schwab_like.api.order_api import (
        SENT_NATIVE_PAYLOADS,
        install_mock_schwab_like_translator,
    )

    install_mock_schwab_like_translator()
    _seed_aapl_msft("_mock_schwab_like")

    resp = flask_app.test_client().post("/api/v2/orders/combo", json=_otoco_body())
    assert resp.status_code == 200, resp.get_json()
    body = resp.get_json()["data"]
    assert body["combo_type"] == "OTOCO"
    assert body["link_id"] == "TEST-LINK-1"
    assert len(body["legs"]) == 3
    # Verify the native payload was captured.
    assert SENT_NATIVE_PAYLOADS, "send_native should have been called"
    sent = SENT_NATIVE_PAYLOADS[-1]
    assert sent["orderStrategyType"] == "TRIGGER_AND_OCO"
    assert sent["link_id"] == "TEST-LINK-1"
    assert len(sent["orderLegCollection"]) == 3


def test_combo_oco_dispatch_to_webull_like(flask_app, monkeypatch):
    monkeypatch.setenv("API_V2__MOCK_WEBULL_LIKE", "1")
    _install_fake_auth_resolver(monkeypatch, "_mock_webull_like")
    _stub_caps(
        monkeypatch,
        broker_code="_mock_webull_like",
        supports_combo_types=["OCO", "OTOCO"],
    )
    from broker._mock_webull_like.api.order_api import (
        SENT_NATIVE_PAYLOADS,
        install_mock_webull_like_translator,
    )

    install_mock_webull_like_translator()
    _seed_aapl_msft("_mock_webull_like")

    body = {
        "apikey": "k",
        "combo_type": "OCO",
        "time_in_force": "DAY",
        "session": "REGULAR",
        "link_id": "WB-OCO-1",
        "legs": [
            {
                "instrument_ref": {"venue_code": "XNAS", "canonical_symbol": "MSFT"},
                "side": "SELL", "quantity": "1", "quantity_unit": "WHOLE",
                "order_type": "LIMIT", "price": "410.00",
            },
            {
                "instrument_ref": {"venue_code": "XNAS", "canonical_symbol": "MSFT"},
                "side": "SELL", "quantity": "1", "quantity_unit": "WHOLE",
                "order_type": "STOP", "trigger_price": "390.00",
            },
        ],
    }
    resp = flask_app.test_client().post("/api/v2/orders/combo", json=body)
    assert resp.status_code == 200, resp.get_json()
    sent = SENT_NATIVE_PAYLOADS[-1]
    assert sent["combo_type"] == "OCO"
    assert sent["link_id"] == "WB-OCO-1"
    assert len(sent["orders"]) == 2
