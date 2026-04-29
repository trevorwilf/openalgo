"""v6 Phase 7 — Nubra v2 broker translator."""

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

BROKER_CODE = "nubra"

_ORDER_TYPE_MAP: dict[OrderType, str] = {
    OrderType.MARKET: "ORDER_TYPE_REGULAR",
    OrderType.LIMIT: "ORDER_TYPE_REGULAR",
    OrderType.STOP_LIMIT: "ORDER_TYPE_STOPLOSS",
    OrderType.STOP: "ORDER_TYPE_STOPLOSS",
}
_PRODUCT_MAP: dict[str, str] = {
    "CNC": "ORDER_DELIVERY_TYPE_CNC",
    "NRML": "ORDER_DELIVERY_TYPE_CNC",
    "MIS": "ORDER_DELIVERY_TYPE_IDAY",
}
_SIDE_MAP: dict[OrderSide, str] = {
    OrderSide.BUY: "ORDER_SIDE_BUY",
    OrderSide.SELL: "ORDER_SIDE_SELL",
}
_TIF_MAP: dict[TimeInForce, str] = {
    TimeInForce.DAY: "ORDER_VALIDITY_DAY",
    TimeInForce.IOC: "ORDER_VALIDITY_IOC",
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


class NubraOrderTranslator:
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
        return {
            "exchange": str(_ifield(instrument, "venue_code", "exchange") or "NSE").upper(),
            "trading_symbol": str(_ifield(instrument, "broker_symbol", "canonical_symbol") or "X"),
            "instrument_token": str(_ifield(instrument, "broker_token", "token") or ""),
            "side": _SIDE_MAP[order.side],
            "order_type": _ORDER_TYPE_MAP[order.order_type],
            "delivery_type": _native_product(order),
            "validity": _TIF_MAP[order.time_in_force],
            "quantity": int(order.quantity),
            "price": float(order.price) if order.price is not None else 0.0,
            "trigger_price": float(order.trigger_price) if order.trigger_price is not None else 0.0,
        }

    def from_native_order_response(self, payload: dict[str, Any], instrument: Any) -> dict[str, Any]:
        order_id = payload.get("order_id") or payload.get("orderId") or payload.get("orderid")
        if order_id is None:
            raise ValueError(f"Nubra order response missing order_id: {payload!r}")
        return {
            "order_id": str(order_id),
            "status": str(payload.get("status", "ACCEPTED")),
            "native": dict(payload),
        }


def install_nubra_translator() -> NubraOrderTranslator:
    from services.broker_translator_registry import register_broker_translator

    t = NubraOrderTranslator()
    register_broker_translator(t)
    return t


__all__ = ["BROKER_CODE", "NubraOrderTranslator", "install_nubra_translator"]
