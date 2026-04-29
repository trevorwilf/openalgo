"""v6 Phase 7 — Paytm Money v2 broker translator."""

from __future__ import annotations

from typing import Any

from domain.account_context import AccountContext
from domain.broker_translator import BrokerOrderTranslator  # noqa: F401
from domain.enums import (
    OrderSide,
    OrderType,
    PositionEffect,
    QuantityUnit,
    Session,
    TimeInForce,
)
from domain.errors import UnsupportedCapability

BROKER_CODE = "paytm"

_ORDER_TYPE_MAP: dict[OrderType, str] = {
    OrderType.MARKET: "MARKET",
    OrderType.LIMIT: "LIMIT",
    OrderType.STOP_LIMIT: "STOP_LOSS",
    OrderType.STOP: "STOP_LOSS_MARKET",
}
_PRODUCT_MAP: dict[str, str] = {"CNC": "C", "NRML": "M", "MIS": "I"}
_SIDE_MAP: dict[OrderSide, str] = {OrderSide.BUY: "B", OrderSide.SELL: "S"}
_TIF_MAP: dict[TimeInForce, str] = {TimeInForce.DAY: "DAY", TimeInForce.IOC: "IOC"}
_EXCHANGE_MAP: dict[str, str] = {
    "NSE": "NSE", "BSE": "BSE",
    "NFO": "NSE", "BFO": "BSE",
}
_SEGMENT_MAP: dict[str, str] = {
    "NSE": "E", "BSE": "E",
    "NFO": "D", "BFO": "D",
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


def _ifield(instrument: Any, *attrs: str) -> Any:
    for a in attrs:
        v = getattr(instrument, a, None)
        if v:
            return v
    return None


class PaytmOrderTranslator:
    broker_code = BROKER_CODE

    def validate(self, order: Any, instrument: Any, account_ctx: AccountContext) -> None:
        if order.order_type not in _ORDER_TYPE_MAP:
            raise UnsupportedCapability(broker_code=BROKER_CODE, capability_name="order_type", dimension="order_type")
        if order.time_in_force not in _TIF_MAP:
            raise UnsupportedCapability(broker_code=BROKER_CODE, capability_name="tif", dimension="tif")
        if order.session not in _SUPPORTED_SESSIONS:
            raise UnsupportedCapability(broker_code=BROKER_CODE, capability_name="session", dimension="session")
        if order.quantity_unit not in _SUPPORTED_QUANTITY_UNITS:
            raise UnsupportedCapability(broker_code=BROKER_CODE, capability_name="quantity_unit", dimension="quantity_unit")

    def to_native(self, order: Any, instrument: Any, account_ctx: AccountContext) -> dict[str, Any]:
        self.validate(order, instrument, account_ctx)
        exchange = str(_ifield(instrument, "venue_code", "exchange") or "NSE").upper()
        return {
            "txn_type": _SIDE_MAP[order.side],
            "exchange": _EXCHANGE_MAP.get(exchange, "NSE"),
            "segment": _SEGMENT_MAP.get(exchange, "E"),
            "product": _native_product(order),
            "security_id": str(_ifield(instrument, "broker_token", "token") or ""),
            "quantity": int(order.quantity),
            "validity": _TIF_MAP[order.time_in_force],
            "order_type": _ORDER_TYPE_MAP[order.order_type],
            "price": float(order.price) if order.price is not None else 0.0,
            "trigger_price": float(order.trigger_price) if order.trigger_price is not None else 0.0,
            "source": "M",
        }

    def from_native_order_response(self, payload: dict[str, Any], instrument: Any) -> dict[str, Any]:
        data = payload.get("data") or payload
        order_id = data.get("orderNo") or data.get("orderId") or data.get("order_id")
        if order_id is None:
            raise ValueError(f"Paytm order response missing orderNo: {payload!r}")
        return {
            "order_id": str(order_id),
            "status": str(payload.get("status", "ACCEPTED")),
            "native": dict(payload),
        }


def install_paytm_translator() -> PaytmOrderTranslator:
    from services.broker_translator_registry import register_broker_translator

    t = PaytmOrderTranslator()
    register_broker_translator(t)
    return t


__all__ = ["BROKER_CODE", "PaytmOrderTranslator", "install_paytm_translator"]
