"""AlpacaOrderTranslator — combo / bracket / OCO / OTO surface."""

from __future__ import annotations

from decimal import Decimal

import pytest

from broker.alpaca.api.order_api import AlpacaOrderTranslator
from domain.enums import (
    ComboType,
    OrderSide,
    OrderType,
    QuantityUnit,
    Session,
    TimeInForce,
)
from domain.errors import UnsupportedCapability
from domain.instrument_ref import InstrumentRef
from domain.orders import NormalizedComboOrderRequest, OrderLeg


class _Resolved:
    """Mirror tests/broker/alpaca/test_order_translator._Resolved."""

    def __init__(self, symbol="AAPL", venue="XNAS"):
        self.instrument_id = "00000000-0000-0000-0000-000000000001"
        self.venue_code = venue
        self.canonical_symbol = symbol
        self.broker_native_symbol = symbol
        self.broker_native_token = "alpaca-id"
        self.supports_fractional = True
        self.currency = "USD"


def _ctx():
    return type("Ctx", (), {"broker_code": "alpaca", "account_id": "fake"})()


def _leg(
    *,
    order_type=OrderType.LIMIT,
    side=OrderSide.BUY,
    qty="1",
    price=None,
    trigger=None,
):
    return OrderLeg(
        instrument_ref=InstrumentRef(
            venue_code="XNAS", canonical_symbol="AAPL"
        ),
        side=side,
        quantity=Decimal(qty),
        quantity_unit=QuantityUnit.WHOLE,
        order_type=order_type,
        price=Decimal(price) if price is not None else None,
        trigger_price=Decimal(trigger) if trigger is not None else None,
    )


# ---------------------------------------------------------------------------
# validate_combo
# ---------------------------------------------------------------------------


def test_validate_single_combo_one_leg_ok():
    combo = NormalizedComboOrderRequest(
        combo_type=ComboType.SINGLE,
        time_in_force=TimeInForce.DAY,
        session=Session.REGULAR,
        legs=[_leg(price="180.00")],
    )
    AlpacaOrderTranslator().validate_combo(combo, [_Resolved()], _ctx())


def test_validate_otoco_three_legs_ok():
    combo = NormalizedComboOrderRequest(
        combo_type=ComboType.OTOCO,
        time_in_force=TimeInForce.DAY,
        session=Session.REGULAR,
        legs=[
            _leg(order_type=OrderType.LIMIT, price="180.00"),       # entry
            _leg(order_type=OrderType.LIMIT, price="200.00",
                 side=OrderSide.SELL),                              # take_profit
            _leg(order_type=OrderType.STOP, trigger="175.00",
                 side=OrderSide.SELL),                              # stop_loss
        ],
    )
    AlpacaOrderTranslator().validate_combo(
        combo, [_Resolved(), _Resolved(), _Resolved()], _ctx()
    )


def test_validate_oco_two_legs_ok():
    combo = NormalizedComboOrderRequest(
        combo_type=ComboType.OCO,
        time_in_force=TimeInForce.DAY,
        session=Session.REGULAR,
        legs=[
            _leg(order_type=OrderType.LIMIT, price="200.00",
                 side=OrderSide.SELL),
            _leg(order_type=OrderType.STOP, trigger="175.00",
                 side=OrderSide.SELL),
        ],
    )
    AlpacaOrderTranslator().validate_combo(
        combo, [_Resolved(), _Resolved()], _ctx()
    )


def test_validate_oto_two_legs_ok():
    combo = NormalizedComboOrderRequest(
        combo_type=ComboType.OTO,
        time_in_force=TimeInForce.DAY,
        session=Session.REGULAR,
        legs=[
            _leg(order_type=OrderType.LIMIT, price="180.00"),
            _leg(order_type=OrderType.LIMIT, price="200.00",
                 side=OrderSide.SELL),
        ],
    )
    AlpacaOrderTranslator().validate_combo(
        combo, [_Resolved(), _Resolved()], _ctx()
    )


def test_validate_otoco_wrong_leg_count_rejected():
    combo = NormalizedComboOrderRequest(
        combo_type=ComboType.OTOCO,
        time_in_force=TimeInForce.DAY,
        session=Session.REGULAR,
        legs=[
            _leg(order_type=OrderType.LIMIT, price="180.00"),
            _leg(order_type=OrderType.LIMIT, price="200.00",
                 side=OrderSide.SELL),
        ],
    )
    with pytest.raises(UnsupportedCapability):
        AlpacaOrderTranslator().validate_combo(
            combo, [_Resolved(), _Resolved()], _ctx()
        )


def test_validate_otoco_take_profit_must_be_limit():
    combo = NormalizedComboOrderRequest(
        combo_type=ComboType.OTOCO,
        time_in_force=TimeInForce.DAY,
        session=Session.REGULAR,
        legs=[
            _leg(order_type=OrderType.LIMIT, price="180.00"),
            _leg(order_type=OrderType.STOP, trigger="200.00",   # WRONG — should be LIMIT
                 side=OrderSide.SELL),
            _leg(order_type=OrderType.STOP, trigger="175.00",
                 side=OrderSide.SELL),
        ],
    )
    with pytest.raises(UnsupportedCapability):
        AlpacaOrderTranslator().validate_combo(
            combo, [_Resolved(), _Resolved(), _Resolved()], _ctx()
        )


def test_validate_combo_cross_symbol_rejected():
    combo = NormalizedComboOrderRequest(
        combo_type=ComboType.OCO,
        time_in_force=TimeInForce.DAY,
        session=Session.REGULAR,
        legs=[
            _leg(order_type=OrderType.LIMIT, price="200.00",
                 side=OrderSide.SELL),
            _leg(order_type=OrderType.STOP, trigger="175.00",
                 side=OrderSide.SELL),
        ],
    )
    with pytest.raises(UnsupportedCapability):
        AlpacaOrderTranslator().validate_combo(
            combo, [_Resolved(symbol="AAPL"), _Resolved(symbol="TSLA")],
            _ctx(),
        )


# ---------------------------------------------------------------------------
# to_native_combo — payload shape
# ---------------------------------------------------------------------------


def test_otoco_emits_bracket_order_class_and_legs():
    combo = NormalizedComboOrderRequest(
        combo_type=ComboType.OTOCO,
        time_in_force=TimeInForce.DAY,
        session=Session.REGULAR,
        legs=[
            _leg(order_type=OrderType.LIMIT, price="180.00"),
            _leg(order_type=OrderType.LIMIT, price="200.00",
                 side=OrderSide.SELL),
            _leg(order_type=OrderType.STOP_LIMIT, price="174.50",
                 trigger="175.00", side=OrderSide.SELL),
        ],
    )
    body = AlpacaOrderTranslator().to_native_combo(
        combo, [_Resolved(), _Resolved(), _Resolved()], _ctx()
    )
    assert body["order_class"] == "bracket"
    assert body["take_profit"] == {"limit_price": "200.00"}
    assert body["stop_loss"] == {
        "stop_price": "175.00",
        "limit_price": "174.50",
    }
    # Parent fields preserved.
    assert body["type"] == "limit"
    assert body["limit_price"] == "180.00"
    assert body["time_in_force"] == "day"


def test_oco_emits_oco_order_class_with_stop_loss():
    combo = NormalizedComboOrderRequest(
        combo_type=ComboType.OCO,
        time_in_force=TimeInForce.DAY,
        session=Session.REGULAR,
        legs=[
            _leg(order_type=OrderType.LIMIT, price="200.00",
                 side=OrderSide.SELL),
            _leg(order_type=OrderType.STOP, trigger="175.00",
                 side=OrderSide.SELL),
        ],
    )
    body = AlpacaOrderTranslator().to_native_combo(
        combo, [_Resolved(), _Resolved()], _ctx()
    )
    assert body["order_class"] == "oco"
    assert body["stop_loss"] == {"stop_price": "175.00"}
    assert "take_profit" not in body


def test_oto_with_limit_child_emits_take_profit():
    combo = NormalizedComboOrderRequest(
        combo_type=ComboType.OTO,
        time_in_force=TimeInForce.DAY,
        session=Session.REGULAR,
        legs=[
            _leg(order_type=OrderType.LIMIT, price="180.00"),
            _leg(order_type=OrderType.LIMIT, price="200.00",
                 side=OrderSide.SELL),
        ],
    )
    body = AlpacaOrderTranslator().to_native_combo(
        combo, [_Resolved(), _Resolved()], _ctx()
    )
    assert body["order_class"] == "oto"
    assert body["take_profit"] == {"limit_price": "200.00"}
    assert "stop_loss" not in body


def test_oto_with_stop_child_emits_stop_loss():
    combo = NormalizedComboOrderRequest(
        combo_type=ComboType.OTO,
        time_in_force=TimeInForce.DAY,
        session=Session.REGULAR,
        legs=[
            _leg(order_type=OrderType.LIMIT, price="180.00"),
            _leg(order_type=OrderType.STOP, trigger="175.00",
                 side=OrderSide.SELL),
        ],
    )
    body = AlpacaOrderTranslator().to_native_combo(
        combo, [_Resolved(), _Resolved()], _ctx()
    )
    assert body["order_class"] == "oto"
    assert body["stop_loss"] == {"stop_price": "175.00"}
    assert "take_profit" not in body


def test_single_combo_collapses_to_plain_order():
    """SINGLE doesn't emit order_class — it's a plain order."""
    combo = NormalizedComboOrderRequest(
        combo_type=ComboType.SINGLE,
        time_in_force=TimeInForce.DAY,
        session=Session.REGULAR,
        legs=[_leg(order_type=OrderType.LIMIT, price="180.00")],
    )
    body = AlpacaOrderTranslator().to_native_combo(
        combo, [_Resolved()], _ctx()
    )
    assert "order_class" not in body
    assert body["type"] == "limit"
    assert body["limit_price"] == "180.00"
