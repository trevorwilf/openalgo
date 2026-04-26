"""Phase 6 v3 (ADR 0022) — end-to-end mock Webull-LIKE flow."""

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

    monkeypatch.setattr("restx_api.v2.orders.resolve_auth", _fake)
    monkeypatch.setattr("restx_api.v2.orders_combo.resolve_auth", _fake)


def _stub_caps_for_webull(monkeypatch):
    from types import SimpleNamespace

    from domain.enums import (
        ComboType,
        OrderType,
        QuantityUnit,
        Session,
        TimeInForce,
    )

    caps = SimpleNamespace(
        broker_code="_mock_webull_like",
        supported_regions=["us"],
        broker_type="US_stock",
        base_currency=None,
        supported_order_types=[OrderType.MARKET, OrderType.LIMIT, OrderType.STOP],
        supported_time_in_force=[TimeInForce.DAY, TimeInForce.GTC],
        supported_sessions=[Session.REGULAR],
        supported_quantity_units=[QuantityUnit.WHOLE],
        supports_combo_types=[ComboType.SINGLE, ComboType.OCO, ComboType.OTOCO],
    )

    def _fake(name):
        return caps if name == "_mock_webull_like" else None

    monkeypatch.setattr("utils.plugin_loader.get_broker_capabilities", _fake)


def test_e2e_mock_webull_single_equity_order(flask_app, monkeypatch):
    monkeypatch.setenv("API_V2__MOCK_WEBULL_LIKE", "1")
    _install_fake_auth_resolver(monkeypatch, "_mock_webull_like")
    _stub_caps_for_webull(monkeypatch)

    from broker._mock_webull_like.api.order_api import (
        SENT_NATIVE_PAYLOADS,
        install_mock_webull_like_translator,
    )
    from broker._mock_webull_like.sync.instrument_sync import run_sync
    from database import broker_rules_repo

    install_mock_webull_like_translator()
    run_sync()

    # Wire the mock Webull auth as the broker-specific account resolver
    # so the dispatcher's resolve_account_context returns an AccountContext
    # with the Webull subaccount_id populated.
    from broker._mock_webull_like.api import auth_api as webull_auth
    from services import account_context_service

    account_context_service._reset_for_tests()
    account_context_service.register_account_resolver(
        webull_auth.BROKER_CODE,
        lambda token, caps: webull_auth.authenticate({"token": token}),
    )

    broker_rules_repo.rules_upsert(
        broker_code="_mock_webull_like",
        venue_code=None,
        asset_class=None,
        session_name=None,
        allowed_order_types=["MARKET", "LIMIT", "STOP"],
        allowed_time_in_force=["DAY", "GTC"],
        allows_fractional=True,
        allows_notional=True,
        allows_short=False,
    )

    body = {
        "apikey": "k",
        "instrument": {"venue_code": "XNAS", "canonical_symbol": "MSFT"},
        "side": "BUY",
        "order_type": "LIMIT",
        "quantity": "5",
        "quantity_unit": "WHOLE",
        "time_in_force": "DAY",
        "price": "400.00",
    }
    with patch("services.place_order_service.place_order_with_auth") as legacy:
        resp = flask_app.test_client().post("/api/v2/orders", json=body)
    assert resp.status_code == 200, resp.get_json()
    out = resp.get_json()["data"]
    assert out["order_id"].startswith("MOCK-WEBULL-")
    legacy.assert_not_called()
    sent = SENT_NATIVE_PAYLOADS[-1]
    assert sent["combo_type"] == "NORMAL"
    assert sent["subaccount_id"] == "MOCK_SUB_X"


def test_e2e_mock_webull_streaming_handle_lifecycle():
    """Subscribe → 3 events delivered → unsubscribe."""
    import asyncio

    from broker._mock_webull_like.api.stream_api import (
        MockWebullLikeMarketDataStream,
        MockWebullLikeOrderEventStream,
    )
    from domain.enums import StreamTransport

    md = MockWebullLikeMarketDataStream()
    assert md.transport == StreamTransport.MQTT
    received = []

    async def _go():
        async def cb(payload):
            received.append(payload)

        handle = await md.subscribe(
            instruments=["MSFT"], account_ctx=None, on_quote=cb,
        )
        await md.unsubscribe(handle)
        return handle

    handle = asyncio.run(_go())
    assert len(received) == 3
    assert handle in md.unsubscribed_handles

    oe = MockWebullLikeOrderEventStream()
    assert oe.transport == StreamTransport.GRPC
    received_oe = []

    async def _go_oe():
        async def cb(payload):
            received_oe.append(payload)

        h = await oe.subscribe(account_ctx=None, on_order_event=cb)
        await oe.unsubscribe(h)
        return h

    h = asyncio.run(_go_oe())
    assert len(received_oe) == 1
    assert h in oe.unsubscribed_handles
