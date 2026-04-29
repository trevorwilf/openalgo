"""v6 Phase 6 — Definedge Securities v2 broker translator."""

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

BROKER_CODE = "definedge"

_PRICE_TYPE_MAP: dict[OrderType, str] = {
    OrderType.MARKET: "MARKET",
    OrderType.LIMIT: "LIMIT",
    OrderType.STOP_LIMIT: "SL",
    OrderType.STOP: "SL-M",
}

_PRODUCT_MAP: dict[str, str] = {
    "CNC": "CNC",
    "NRML": "NRML",
    "MIS": "INTRADAY",
}

_TIF_MAP: dict[TimeInForce, str] = {TimeInForce.DAY: "DAY", TimeInForce.IOC: "IOC"}
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


class DefinedgeOrderTranslator:
    broker_code = BROKER_CODE

    def validate(self, order: Any, instrument: Any, account_ctx: AccountContext) -> None:
        if order.order_type not in _PRICE_TYPE_MAP:
            raise UnsupportedCapability(
                broker_code=BROKER_CODE, capability_name="order_type", dimension="order_type",
            )
        if order.time_in_force not in _TIF_MAP:
            raise UnsupportedCapability(broker_code=BROKER_CODE, capability_name="tif", dimension="tif")
        if order.session not in _SUPPORTED_SESSIONS:
            raise UnsupportedCapability(broker_code=BROKER_CODE, capability_name="session", dimension="session")
        if order.quantity_unit not in _SUPPORTED_QUANTITY_UNITS:
            raise UnsupportedCapability(
                broker_code=BROKER_CODE, capability_name="quantity_unit", dimension="quantity_unit",
            )

    def to_native(self, order: Any, instrument: Any, account_ctx: AccountContext) -> dict[str, Any]:
        self.validate(order, instrument, account_ctx)
        out: dict[str, Any] = {
            "tradingsymbol": str(_ifield(instrument, "broker_symbol", "canonical_symbol") or "X"),
            "exchange": str(_ifield(instrument, "venue_code", "exchange") or "NSE").upper(),
            "quantity": str(int(order.quantity))
            if order.quantity == order.quantity.to_integral_value()
            else str(order.quantity),
            "price": str(order.price) if order.price is not None else "0",
            "price_type": _PRICE_TYPE_MAP[order.order_type],
            "product_type": _native_product(order),
            "order_type": order.side.value.upper(),
        }
        if order.trigger_price is not None and order.order_type in (OrderType.STOP, OrderType.STOP_LIMIT):
            out["trigger_price"] = str(order.trigger_price)
        return out

    def from_native_order_response(self, payload: dict[str, Any], instrument: Any) -> dict[str, Any]:
        order_id = payload.get("order_id") or payload.get("orderid") or payload.get("orderId")
        if order_id is None:
            raise ValueError(f"Definedge order response missing order id: {payload!r}")
        return {
            "order_id": str(order_id),
            "status": str(payload.get("status", "ACCEPTED")),
            "native": dict(payload),
        }


def install_definedge_translator() -> DefinedgeOrderTranslator:
    from services.broker_translator_registry import register_broker_translator

    t = DefinedgeOrderTranslator()
    register_broker_translator(t)
    return t


__all__ = ["BROKER_CODE", "DefinedgeOrderTranslator", "install_definedge_translator"]
