"""Phase 8 — architecture readiness checks.

These tests verify the framework supports the surfaces Schwab and
Webull broker plugins will need, without any plugin actually being
installed. Failure here means a future broker plugin would not have
the building blocks it needs.
"""

from __future__ import annotations

from decimal import Decimal

import pytest

from domain.account_context import AccountContext
from domain.broker_streaming import (
    BrokerMarketDataStream,
    BrokerOrderEventStream,
)
from domain.capabilities import BrokerCapabilities, ProductCapabilities
from domain.currency import Currency
from domain.enums import (
    AssetClass,
    AuthMode,
    ComboType,
    MarketFamily,
    OrderSide,
    OrderType,
    QuantityUnit,
    Session,
    StreamTransport,
    TimeInForce,
)
from domain.instrument_ref import InstrumentRef
from domain.orders import NormalizedComboOrderRequest, OrderLeg


# ---- Combo orders --------------------------------------------------


def _ref() -> InstrumentRef:
    return InstrumentRef(venue_code="XNAS", canonical_symbol="AAPL")


def _market_leg() -> OrderLeg:
    return OrderLeg(
        instrument_ref=_ref(),
        side=OrderSide.BUY,
        quantity=Decimal("1"),
        quantity_unit=QuantityUnit.WHOLE,
        order_type=OrderType.MARKET,
    )


def _limit_leg(price: str) -> OrderLeg:
    return OrderLeg(
        instrument_ref=_ref(),
        side=OrderSide.SELL,
        quantity=Decimal("1"),
        quantity_unit=QuantityUnit.WHOLE,
        order_type=OrderType.LIMIT,
        price=Decimal(price),
    )


def test_combo_order_model_supports_oto_oco_otoco():
    """Schwab OrderStrategyType requires OTO, OCO, and OTOCO."""
    NormalizedComboOrderRequest(
        combo_type=ComboType.OTO,
        time_in_force=TimeInForce.DAY,
        session=Session.REGULAR,
        legs=[_market_leg(), _limit_leg("110")],
    )
    NormalizedComboOrderRequest(
        combo_type=ComboType.OCO,
        time_in_force=TimeInForce.DAY,
        session=Session.REGULAR,
        legs=[_limit_leg("110"), _limit_leg("90")],
    )
    NormalizedComboOrderRequest(
        combo_type=ComboType.OTOCO,
        time_in_force=TimeInForce.DAY,
        session=Session.REGULAR,
        legs=[_market_leg(), _limit_leg("120"), _limit_leg("90")],
    )


# ---- Streaming -----------------------------------------------------


def test_streaming_contract_supports_websocket_mqtt_grpc():
    """Webull MQTT, Schwab WebSocket, Webull gRPC must all be expressible."""
    assert StreamTransport.WEBSOCKET.value == "WEBSOCKET"
    assert StreamTransport.MQTT.value == "MQTT"
    assert StreamTransport.GRPC.value == "GRPC"

    class _DummyStream:
        broker_code = "x"
        transport = StreamTransport.MQTT

        async def subscribe(self, *args, **kwargs):
            from domain.broker_streaming import SubscriptionHandle

            return SubscriptionHandle("x", StreamTransport.MQTT, "1")

        async def unsubscribe(self, h):
            pass

    assert isinstance(_DummyStream(), BrokerMarketDataStream)
    assert isinstance(_DummyStream(), BrokerOrderEventStream)


# ---- Per-product capability matrix --------------------------------


def test_product_capability_matrix_supports_per_product_diffs():
    eq = ProductCapabilities(
        asset_class=AssetClass.EQUITY,
        supported_quantity_units=[QuantityUnit.WHOLE, QuantityUnit.FRACTIONAL],
        supports_fractional=True,
    )
    fut = ProductCapabilities(
        asset_class=AssetClass.FUTURE,
        supported_quantity_units=[QuantityUnit.CONTRACTS],
        supports_fractional=False,
    )
    caps = BrokerCapabilities(
        broker_code="webull",
        broker_display_name="Webull",
        market_families=[MarketFamily.US_STOCK],
        supported_regions=["us"],
        supported_venue_codes=["XNAS"],
        supported_asset_classes=[AssetClass.EQUITY, AssetClass.FUTURE],
        supported_order_types=[OrderType.MARKET],
        supported_time_in_force=[TimeInForce.DAY],
        supported_sessions=[Session.REGULAR],
        supported_quantity_units=[QuantityUnit.WHOLE, QuantityUnit.CONTRACTS],
        trading_currencies=[Currency.USD],
        base_currency=Currency.USD,
        products=[eq, fut],
    )
    assert {p.asset_class for p in caps.products} == {AssetClass.EQUITY, AssetClass.FUTURE}
    assert any(p.supports_fractional for p in caps.products if p.asset_class == AssetClass.EQUITY)
    assert not any(p.supports_fractional for p in caps.products if p.asset_class == AssetClass.FUTURE)


# ---- Account context ----------------------------------------------


def test_account_context_supports_account_hash():
    """Schwab account-hash addressing is representable."""
    ctx = AccountContext(
        broker_code="schwab",
        account_id="ACCT-1234",
        account_hash="aabbccdd-1122",
        base_currency=Currency.USD,
    )
    assert ctx.account_hash == "aabbccdd-1122"


def test_account_context_supports_subaccounts():
    """Webull-style sub-accounts are representable."""
    ctx = AccountContext(
        broker_code="webull",
        account_id="MAIN-1",
        subaccount_id="OPT-1",
        base_currency=Currency.USD,
    )
    assert ctx.subaccount_id == "OPT-1"


def test_account_context_supports_entitlements():
    """Real-time market data entitlements addressable."""
    ctx = AccountContext(
        broker_code="schwab",
        account_id="A",
        entitlements=["us_equity_realtime", "options_l1"],
    )
    assert "us_equity_realtime" in ctx.entitlements


# ---- Auth modes ----------------------------------------------------


def test_capabilities_support_auth_modes_signature_oauth():
    """Webull-direct (signature) and Webull-Connect / Schwab (OAuth)
    are expressible through the AuthMode enum."""
    caps = BrokerCapabilities(
        broker_code="webull",
        broker_display_name="Webull",
        market_families=[MarketFamily.US_STOCK],
        supported_regions=["us"],
        supported_venue_codes=["XNAS"],
        supported_asset_classes=[AssetClass.EQUITY],
        supported_order_types=[OrderType.MARKET],
        supported_time_in_force=[TimeInForce.DAY],
        supported_sessions=[Session.REGULAR],
        supported_quantity_units=[QuantityUnit.WHOLE],
        trading_currencies=[Currency.USD],
        base_currency=Currency.USD,
        auth_modes=[AuthMode.SIGNATURE, AuthMode.OAUTH],
    )
    assert AuthMode.SIGNATURE in caps.auth_modes
    assert AuthMode.OAUTH in caps.auth_modes
