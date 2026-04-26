"""Phase 6 v3 (ADR 0022) — end-to-end mock Schwab-LIKE flow.

Drives the full promoted dispatch (auth → resolver → translator →
send_native) through /api/v2/orders for a single-leg equity order
and through /api/v2/orders/combo for an OTOCO order. Asserts the
legacy India services were never called.
"""

from __future__ import annotations

from unittest.mock import patch

import pytest

from services.broker_market_data_registry import (
    clear_market_data_registries_for_tests,
)
from services.broker_translator_registry import clear_registry_for_tests


@pytest.fixture(autouse=True)
def _clean_registries():
    clear_market_data_registries_for_tests()
    clear_registry_for_tests()
    yield
    clear_market_data_registries_for_tests()
    clear_registry_for_tests()


def _install_fake_auth_resolver(monkeypatch, broker_code: str):
    def _fake():
        return "fake-token", broker_code, None

    # Patch the resolver in every v2 namespace that needs it.
    monkeypatch.setattr("restx_api.v2.orders.resolve_auth", _fake)
    monkeypatch.setattr("restx_api.v2.orders_combo.resolve_auth", _fake)


def _stub_caps_for_schwab(monkeypatch):
    from types import SimpleNamespace

    from domain.enums import (
        ComboType,
        OrderType,
        QuantityUnit,
        Session,
        TimeInForce,
    )

    caps = SimpleNamespace(
        broker_code="_mock_schwab_like",
        supported_regions=["us"],
        broker_type="US_stock",
        base_currency=None,
        supported_order_types=[OrderType.MARKET, OrderType.LIMIT],
        supported_time_in_force=[TimeInForce.DAY, TimeInForce.GTC],
        supported_sessions=[Session.REGULAR],
        supported_quantity_units=[QuantityUnit.WHOLE],
        supports_combo_types=[
            ComboType.SINGLE,
            ComboType.OTO,
            ComboType.OCO,
            ComboType.OTOCO,
            ComboType.MULTILEG_OPTIONS,
        ],
    )

    def _fake(name):
        return caps if name == "_mock_schwab_like" else None

    monkeypatch.setattr("utils.plugin_loader.get_broker_capabilities", _fake)


def test_e2e_mock_schwab_single_equity_order(flask_app, monkeypatch):
    """Place a single-leg AAPL BUY market order through /api/v2/orders.

    Asserts legacy place_order_service is never called and the
    response carries the mock-translator's order id.
    """
    monkeypatch.setenv("API_V2__MOCK_SCHWAB_LIKE", "1")
    _install_fake_auth_resolver(monkeypatch, "_mock_schwab_like")
    _stub_caps_for_schwab(monkeypatch)

    from broker._mock_schwab_like.api.order_api import (
        SENT_NATIVE_PAYLOADS,
        install_mock_schwab_like_translator,
    )
    from broker._mock_schwab_like.sync.instrument_sync import run_sync
    from database import broker_rules_repo

    install_mock_schwab_like_translator()
    run_sync()
    # Seed a permissive rule so check_order doesn't reject.
    broker_rules_repo.rules_upsert(
        broker_code="_mock_schwab_like",
        venue_code=None,
        asset_class=None,
        session_name=None,
        allowed_order_types=["MARKET", "LIMIT"],
        allowed_time_in_force=["DAY", "GTC"],
        allows_fractional=True,
        allows_notional=True,
        allows_short=True,
    )

    body = {
        "apikey": "k",
        "instrument": {"venue_code": "XNAS", "canonical_symbol": "AAPL"},
        "side": "BUY",
        "order_type": "MARKET",
        "quantity": "10",
        "quantity_unit": "WHOLE",
        "time_in_force": "DAY",
    }
    with patch("services.place_order_service.place_order_with_auth") as legacy:
        resp = flask_app.test_client().post("/api/v2/orders", json=body)
    assert resp.status_code == 200, resp.get_json()
    out = resp.get_json()["data"]
    assert out["order_id"].startswith("MOCK-SCHWAB-")
    assert out["status"] == "ACCEPTED"
    legacy.assert_not_called()
    assert SENT_NATIVE_PAYLOADS, "send_native should have run"


def test_e2e_mock_schwab_otoco_combo_order(flask_app, monkeypatch):
    """Place an OTOCO combo order through /api/v2/orders/combo."""
    monkeypatch.setenv("API_V2__MOCK_SCHWAB_LIKE", "1")
    _install_fake_auth_resolver(monkeypatch, "_mock_schwab_like")
    _stub_caps_for_schwab(monkeypatch)

    from broker._mock_schwab_like.api.order_api import (
        SENT_NATIVE_PAYLOADS,
        install_mock_schwab_like_translator,
    )
    from broker._mock_schwab_like.sync.instrument_sync import run_sync

    install_mock_schwab_like_translator()
    run_sync()

    body = {
        "apikey": "k",
        "combo_type": "OTOCO",
        "time_in_force": "DAY",
        "session": "REGULAR",
        "link_id": "E2E-OTOCO",
        "legs": [
            {
                "instrument_ref": {"venue_code": "XNAS", "canonical_symbol": "AAPL"},
                "side": "BUY", "quantity": "1", "quantity_unit": "WHOLE",
                "order_type": "LIMIT", "price": "150.00",
            },
            {
                "instrument_ref": {"venue_code": "XNAS", "canonical_symbol": "AAPL"},
                "side": "SELL", "quantity": "1", "quantity_unit": "WHOLE",
                "order_type": "LIMIT", "price": "155.00",
            },
            {
                "instrument_ref": {"venue_code": "XNAS", "canonical_symbol": "AAPL"},
                "side": "SELL", "quantity": "1", "quantity_unit": "WHOLE",
                "order_type": "STOP", "trigger_price": "145.00",
            },
        ],
    }
    with patch("services.place_order_service.place_order_with_auth") as legacy:
        resp = flask_app.test_client().post("/api/v2/orders/combo", json=body)
    assert resp.status_code == 200, resp.get_json()
    out = resp.get_json()["data"]
    assert out["combo_type"] == "OTOCO"
    assert len(out["legs"]) == 3
    legacy.assert_not_called()
    sent = SENT_NATIVE_PAYLOADS[-1]
    assert sent["orderStrategyType"] == "TRIGGER_AND_OCO"
