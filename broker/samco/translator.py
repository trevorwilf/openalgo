"""v6 Phase 7 — Samco v2 broker translator."""

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

BROKER_CODE = "samco"

_ORDER_TYPE_MAP: dict[OrderType, str] = {
    OrderType.MARKET: "MKT",
    OrderType.LIMIT: "L",
    OrderType.STOP_LIMIT: "SL",
    OrderType.STOP: "SL-M",
}
_PRODUCT_MAP: dict[str, str] = {"CNC": "CNC", "NRML": "NRML", "MIS": "MIS"}
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


class SamcoOrderTranslator:
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
            "tradingSymbol": str(_ifield(instrument, "broker_symbol", "canonical_symbol") or "X"),
            "transactionType": order.side.value.upper(),
            "orderType": _ORDER_TYPE_MAP[order.order_type],
            "productType": _native_product(order),
            "quantity": str(int(order.quantity)),
            "orderValidity": _TIF_MAP[order.time_in_force],
            "price": str(order.price) if order.price is not None else "0",
            "triggerPrice": str(order.trigger_price) if order.trigger_price is not None else "0",
            "disclosedQuantity": "0",
            "afterMarketOrderFlag": "NO",
        }

    def from_native_order_response(self, payload: dict[str, Any], instrument: Any) -> dict[str, Any]:
        order_id = payload.get("orderNumber") or payload.get("orderId") or payload.get("order_id")
        if order_id is None:
            raise ValueError(f"Samco order response missing orderNumber: {payload!r}")
        return {
            "order_id": str(order_id),
            "status": str(payload.get("status") or payload.get("orderStatus", "ACCEPTED")),
            "native": dict(payload),
        }


def install_samco_translator() -> SamcoOrderTranslator:
    from services.broker_translator_registry import register_broker_translator

    t = SamcoOrderTranslator()
    register_broker_translator(t)
    return t


__all__ = ["BROKER_CODE", "SamcoOrderTranslator", "install_samco_translator"]
