"""v6 Phase 5 — Angel Broking (Smart API) v2 broker translator.

Bit-identical with the legacy v1 ``broker.angel.mapping.transform_data``
shape for every order the v1 lane currently accepts. Native fields:
``variety`` + ``ordertype`` + ``producttype`` (DELIVERY / CARRYFORWARD /
INTRADAY) + ``transactiontype`` + ``symboltoken``.
"""

from __future__ import annotations

from typing import Any

from domain.account_context import AccountContext
from domain.broker_translator import BrokerOrderTranslator  # noqa: F401
from domain.enums import (
    OrderType,
    PositionEffect,
    QuantityUnit,
    Session,
    TimeInForce,
)
from domain.errors import UnsupportedCapability

BROKER_CODE = "angel"

_ORDER_TYPE_MAP: dict[OrderType, str] = {
    OrderType.MARKET: "MARKET",
    OrderType.LIMIT: "LIMIT",
    OrderType.STOP_LIMIT: "STOPLOSS_LIMIT",
    OrderType.STOP: "STOPLOSS_MARKET",
}

_VARIETY_MAP: dict[OrderType, str] = {
    OrderType.MARKET: "NORMAL",
    OrderType.LIMIT: "NORMAL",
    OrderType.STOP_LIMIT: "STOPLOSS",
    OrderType.STOP: "STOPLOSS",
}

_PRODUCT_MAP: dict[str, str] = {
    "CNC": "DELIVERY",
    "NRML": "CARRYFORWARD",
    "MIS": "INTRADAY",
}

_TIF_MAP: dict[TimeInForce, str] = {
    TimeInForce.DAY: "DAY",
    TimeInForce.IOC: "IOC",
}

_SUPPORTED_QUANTITY_UNITS = frozenset({QuantityUnit.WHOLE, QuantityUnit.LOTS})
_SUPPORTED_SESSIONS = frozenset({Session.REGULAR})


def _native_product(order: Any) -> str:
    if order.position_effect == PositionEffect.REDUCE_ONLY:
        return _PRODUCT_MAP["MIS"]
    hint = (order.extra or {}).get("legacy_product_hint")
    if isinstance(hint, str) and hint.upper() in _PRODUCT_MAP:
        return _PRODUCT_MAP[hint.upper()]
    return _PRODUCT_MAP["CNC"]


def _instrument_field(instrument: Any, *attrs: str) -> Any:
    for a in attrs:
        v = getattr(instrument, a, None)
        if v:
            return v
    return None


class AngelOrderTranslator:
    broker_code = BROKER_CODE

    def validate(self, order: Any, instrument: Any, account_ctx: AccountContext) -> None:
        if order.order_type not in _ORDER_TYPE_MAP:
            raise UnsupportedCapability(
                broker_code=BROKER_CODE,
                capability_name="order_type",
                details=f"order_type={order.order_type.value} not supported by Angel",
                dimension="order_type",
            )
        if order.time_in_force not in _TIF_MAP:
            raise UnsupportedCapability(
                broker_code=BROKER_CODE,
                capability_name="time_in_force",
                details=f"time_in_force={order.time_in_force.value} not supported",
                dimension="tif",
            )
        if order.session not in _SUPPORTED_SESSIONS:
            raise UnsupportedCapability(
                broker_code=BROKER_CODE,
                capability_name="session",
                details=f"session={order.session.value} not supported",
                dimension="session",
            )
        if order.quantity_unit not in _SUPPORTED_QUANTITY_UNITS:
            raise UnsupportedCapability(
                broker_code=BROKER_CODE,
                capability_name="quantity_unit",
                details=f"quantity_unit={order.quantity_unit.value} not supported",
                dimension="quantity_unit",
            )

    def to_native(self, order: Any, instrument: Any, account_ctx: AccountContext) -> dict[str, Any]:
        self.validate(order, instrument, account_ctx)
        symboltoken = _instrument_field(instrument, "broker_token", "token", "symboltoken") or ""
        tradingsymbol = _instrument_field(
            instrument, "broker_symbol", "brsymbol", "canonical_symbol", "symbol"
        ) or "X"
        exchange = _instrument_field(
            instrument, "venue_code", "exchange", "brexchange"
        ) or "NSE"
        return {
            "variety": _VARIETY_MAP[order.order_type],
            "tradingsymbol": str(tradingsymbol),
            "symboltoken": str(symboltoken),
            "transactiontype": order.side.value.upper(),
            "exchange": str(exchange).upper(),
            "ordertype": _ORDER_TYPE_MAP[order.order_type],
            "producttype": _native_product(order),
            "duration": _TIF_MAP[order.time_in_force],
            "price": str(order.price) if order.price is not None else "0",
            "squareoff": "0",
            "stoploss": str(order.trigger_price) if order.trigger_price is not None else "0",
            "triggerprice": str(order.trigger_price) if order.trigger_price is not None else "0",
            "disclosedquantity": "0",
            "quantity": str(int(order.quantity))
            if order.quantity == order.quantity.to_integral_value()
            else str(order.quantity),
        }

    def from_native_order_response(self, payload: dict[str, Any], instrument: Any) -> dict[str, Any]:
        # Angel SmartAPI returns {"data": {"orderid": "..."}, "status": True/False}
        data = payload.get("data") or {}
        order_id = data.get("orderid") or payload.get("orderid") or payload.get("order_id")
        if order_id is None:
            raise ValueError(f"Angel order response missing orderid: {payload!r}")
        return {
            "order_id": str(order_id),
            "status": "ACCEPTED" if payload.get("status", True) else "REJECTED",
            "native": dict(payload),
        }


def install_angel_translator() -> AngelOrderTranslator:
    from services.broker_translator_registry import register_broker_translator

    t = AngelOrderTranslator()
    register_broker_translator(t)
    return t


__all__ = ["BROKER_CODE", "AngelOrderTranslator", "install_angel_translator"]
