"""v6 Phase 5-bis — promoted MPP service contract tests."""

from __future__ import annotations

from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from domain.account_context import AccountContext
from domain.currency import Currency
from domain.enums import (
    OrderSide,
    OrderType,
    PositionEffect,
    QuantityUnit,
    Session,
    TimeInForce,
)
from domain.instrument_ref import InstrumentRef
from domain.orders import NormalizedOrderRequest
from services.promoted_mpp_service import (
    LEGACY_INDIA_MPP_MARKET_BROKERS,
    LEGACY_INDIA_MPP_SLM_BROKERS,
    apply_mpp_if_required,
    requires_mpp_market,
    requires_mpp_slm,
)

# Phase 5 (T-22) — alias the renamed inventory frozensets so the
# existing parametrized tests keep working. The runtime behavior is
# now capability-driven (each broker plugin declares
# ``requires_market_price_protection`` / ``requires_slm_to_sl_conversion``);
# the inventory below is the documentation snapshot of which India
# brokers historically needed MPP.
BROKERS_REQUIRING_MPP_MARKET = LEGACY_INDIA_MPP_MARKET_BROKERS
BROKERS_REQUIRING_MPP_SLM = LEGACY_INDIA_MPP_SLM_BROKERS


def _make_order(
    *,
    order_type: OrderType = OrderType.MARKET,
    side: OrderSide = OrderSide.BUY,
    quantity: str = "10",
    price: str | None = None,
    trigger_price: str | None = None,
    symbol: str = "RELIANCE",
    venue: str = "NSE",
) -> NormalizedOrderRequest:
    return NormalizedOrderRequest(
        instrument=InstrumentRef(canonical_symbol=symbol, venue_code=venue),
        side=side,
        order_type=order_type,
        quantity=Decimal(quantity),
        quantity_unit=QuantityUnit.WHOLE,
        price=Decimal(price) if price is not None else None,
        trigger_price=Decimal(trigger_price) if trigger_price is not None else None,
        time_in_force=TimeInForce.DAY,
        session=Session.REGULAR,
        position_effect=PositionEffect.NONE,
    )


def _stub_instrument(symbol: str = "RELIANCE", venue: str = "NSE") -> SimpleNamespace:
    return SimpleNamespace(
        broker_symbol=symbol,
        canonical_symbol=symbol,
        venue_code=venue,
    )


def test_known_brokers_match_v1_transform_data_behavior() -> None:
    """The 9 brokers whose v1 transform_data applies MARKET MPP."""
    expected = {
        "flattrade", "motilal", "pocketful", "samco", "kotak",
        "ibulls", "indmoney", "shoonya", "zebu",
    }
    assert BROKERS_REQUIRING_MPP_MARKET == expected


def test_brokers_requiring_slm_mpp() -> None:
    """The 2 brokers (motilal, samco) whose v1 also converts SL-M → SL."""
    assert BROKERS_REQUIRING_MPP_SLM == {"motilal", "samco"}


@pytest.mark.parametrize("broker", sorted(BROKERS_REQUIRING_MPP_MARKET))
def test_requires_mpp_market_true_for_known_brokers(broker: str) -> None:
    assert requires_mpp_market(broker) is True


@pytest.mark.parametrize("broker", ["zerodha", "angel", "dhan", "fyers", "upstox"])
def test_requires_mpp_market_false_for_other_brokers(broker: str) -> None:
    assert requires_mpp_market(broker) is False


def test_no_op_when_broker_doesnt_need_mpp() -> None:
    """Zerodha doesn't need MPP. The order passes through unchanged."""
    order = _make_order(order_type=OrderType.MARKET)
    out = apply_mpp_if_required(
        order, broker_code="zerodha", instrument=_stub_instrument(), auth_token="t",
    )
    assert out is order


def test_no_op_when_order_is_not_market_or_stop() -> None:
    """LIMIT orders pass through unchanged for any broker."""
    order = _make_order(order_type=OrderType.LIMIT, price="100.00")
    out = apply_mpp_if_required(
        order, broker_code="flattrade", instrument=_stub_instrument(), auth_token="t",
    )
    assert out is order


def test_no_op_when_auth_token_missing() -> None:
    """Without auth_token we can't fetch a quote — pass through."""
    order = _make_order(order_type=OrderType.MARKET)
    out = apply_mpp_if_required(
        order, broker_code="flattrade", instrument=_stub_instrument(), auth_token=None,
    )
    assert out is order


def test_no_op_when_quote_fetch_fails() -> None:
    """When the broker's BrokerData class throws, pass through unchanged."""
    order = _make_order(order_type=OrderType.MARKET)
    with patch(
        "services.promoted_mpp_service._fetch_ltp_and_tick",
        return_value=(None, None),
    ):
        out = apply_mpp_if_required(
            order, broker_code="flattrade", instrument=_stub_instrument(), auth_token="t",
        )
    assert out is order


def test_no_op_when_ltp_is_zero() -> None:
    order = _make_order(order_type=OrderType.MARKET)
    with patch(
        "services.promoted_mpp_service._fetch_ltp_and_tick",
        return_value=(0.0, 0.05),
    ):
        out = apply_mpp_if_required(
            order, broker_code="flattrade", instrument=_stub_instrument(), auth_token="t",
        )
    assert out is order


def test_market_buy_converts_to_limit_with_protected_buy_price() -> None:
    """MARKET BUY → LIMIT with price = LTP * (1 + slab%)."""
    # Use SBIN instead of RELIANCE — RELIANCE ends in "CE" which the
    # naive get_instrument_type_from_symbol misclassifies as a call
    # option (a known mpp_slab.py limitation; out of scope here).
    order = _make_order(
        order_type=OrderType.MARKET,
        side=OrderSide.BUY,
        quantity="10",
        symbol="SBIN",
    )
    # LTP = 1000 → EQ slab is 0.5% (price > 500) → buy = 1000 * 1.005 = 1005.0
    with patch(
        "services.promoted_mpp_service._fetch_ltp_and_tick",
        return_value=(1000.0, 0.05),
    ):
        out = apply_mpp_if_required(
            order, broker_code="flattrade", instrument=_stub_instrument("SBIN"), auth_token="t",
        )
    assert out is not order
    assert out.order_type == OrderType.LIMIT
    assert out.price == Decimal("1005.00")
    # Other fields preserved
    assert out.quantity == Decimal("10")
    assert out.side == OrderSide.BUY


def test_market_sell_converts_to_limit_with_protected_sell_price() -> None:
    """MARKET SELL → LIMIT with price = LTP * (1 - slab%)."""
    order = _make_order(order_type=OrderType.MARKET, side=OrderSide.SELL, symbol="SBIN")
    with patch(
        "services.promoted_mpp_service._fetch_ltp_and_tick",
        return_value=(1000.0, 0.05),
    ):
        out = apply_mpp_if_required(
            order, broker_code="shoonya", instrument=_stub_instrument("SBIN"), auth_token="t",
        )
    assert out.order_type == OrderType.LIMIT
    assert out.price == Decimal("995.00")
    assert out.side == OrderSide.SELL


def test_slm_converts_to_stop_limit_for_motilal() -> None:
    """For motilal (and samco) STOP → STOP_LIMIT using trigger_price + slab."""
    order = _make_order(
        order_type=OrderType.STOP,
        side=OrderSide.SELL,
        trigger_price="1000.00",
        symbol="SBIN",
    )
    out = apply_mpp_if_required(
        order, broker_code="motilal", instrument=_stub_instrument("SBIN"), auth_token="t",
    )
    # Trigger 1000 SELL → 1000 * (1 - 0.005) = 995.0 (no tick rounding without tick_size)
    assert out is not order
    assert out.order_type == OrderType.STOP_LIMIT
    assert out.price is not None and out.price > Decimal("0")
    # Trigger price preserved
    assert out.trigger_price == Decimal("1000.00")


def test_slm_skipped_for_brokers_not_in_slm_set() -> None:
    """flattrade is in MARKET set but not SLM set; STOP passes through."""
    order = _make_order(order_type=OrderType.STOP, trigger_price="1000.00", symbol="SBIN")
    out = apply_mpp_if_required(
        order, broker_code="flattrade", instrument=_stub_instrument("SBIN"), auth_token="t",
    )
    assert out is order  # unchanged


def test_operator_can_disable_mpp_for_a_broker(monkeypatch) -> None:
    """API_V2_MPP_FLATTRADE=0 disables MPP for that broker."""
    monkeypatch.setenv("API_V2_MPP_FLATTRADE", "0")
    order = _make_order(order_type=OrderType.MARKET, symbol="SBIN")
    with patch(
        "services.promoted_mpp_service._fetch_ltp_and_tick",
        return_value=(1000.0, 0.05),
    ):
        out = apply_mpp_if_required(
            order, broker_code="flattrade", instrument=_stub_instrument("SBIN"), auth_token="t",
        )
    assert out is order  # unchanged because operator disabled


def test_options_uses_options_mpp_slabs() -> None:
    """Options symbols use the OPT slab table (CE/PE → 1-5% by price)."""
    order = _make_order(
        order_type=OrderType.MARKET,
        symbol="NIFTY28MAR2420800CE",
        venue="NFO",
    )
    # LTP = 5 (CE, < 10) → 5% slab → BUY = 5 * 1.05 = 5.25
    with patch(
        "services.promoted_mpp_service._fetch_ltp_and_tick",
        return_value=(5.0, 0.05),
    ):
        out = apply_mpp_if_required(
            order, broker_code="shoonya",
            instrument=_stub_instrument("NIFTY28MAR2420800CE", "NFO"),
            auth_token="t",
        )
    assert out.order_type == OrderType.LIMIT
    # 5.25 rounded to tick 0.05 = 5.25
    assert out.price == Decimal("5.25")


def test_passthrough_when_broker_code_is_blank() -> None:
    order = _make_order(order_type=OrderType.MARKET)
    out = apply_mpp_if_required(
        order, broker_code="", instrument=_stub_instrument(), auth_token="t",
    )
    assert out is order
