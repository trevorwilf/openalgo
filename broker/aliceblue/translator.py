"""v6 Phase 6 — AliceBlue V2 broker translator."""

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

BROKER_CODE = "aliceblue"

_ORDER_TYPE_MAP: dict[OrderType, str] = {
    OrderType.MARKET: "MARKET",
    OrderType.LIMIT: "LIMIT",
    OrderType.STOP_LIMIT: "SL",
    OrderType.STOP: "SLM",
}

_PRODUCT_MAP: dict[str, str] = {
    "CNC": "LONGTERM",
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


class AliceBlueOrderTranslator:
    broker_code = BROKER_CODE

    def validate(self, order: Any, instrument: Any, account_ctx: AccountContext) -> None:
        if order.order_type not in _ORDER_TYPE_MAP:
            raise UnsupportedCapability(
                broker_code=BROKER_CODE, capability_name="order_type",
                details=f"order_type={order.order_type.value} not supported",
                dimension="order_type",
            )
        if order.time_in_force not in _TIF_MAP:
            raise UnsupportedCapability(
                broker_code=BROKER_CODE, capability_name="time_in_force",
                dimension="tif",
            )
        if order.session not in _SUPPORTED_SESSIONS:
            raise UnsupportedCapability(
                broker_code=BROKER_CODE, capability_name="session",
                dimension="session",
            )
        if order.quantity_unit not in _SUPPORTED_QUANTITY_UNITS:
            raise UnsupportedCapability(
                broker_code=BROKER_CODE, capability_name="quantity_unit",
                dimension="quantity_unit",
            )

    def to_native(self, order: Any, instrument: Any, account_ctx: AccountContext) -> dict[str, Any]:
        self.validate(order, instrument, account_ctx)
        return {
            "exchange": str(_ifield(instrument, "venue_code", "exchange") or "NSE").upper(),
            "instrumentId": str(_ifield(instrument, "broker_token", "token") or ""),
            "transactionType": order.side.value.upper(),
            "quantity": int(order.quantity),
            "product": _native_product(order),
            "orderComplexity": "REGULAR",
            "orderType": _ORDER_TYPE_MAP[order.order_type],
            "validity": _TIF_MAP[order.time_in_force],
            "price": str(order.price) if order.price is not None else "0",
            "slLegPrice": "",
            "targetLegPrice": "",
            "slTriggerPrice": str(order.trigger_price) if order.trigger_price is not None else "0",
            "disclosedQuantity": "",
            "marketProtectionPercent": "",
        }

    def from_native_order_response(self, payload: dict[str, Any], instrument: Any) -> dict[str, Any]:
        order_id = payload.get("orderNumber") or payload.get("order_id") or payload.get("orderId")
        if order_id is None:
            raise ValueError(f"AliceBlue order response missing order id: {payload!r}")
        return {
            "order_id": str(order_id),
            "status": str(payload.get("stat") or payload.get("status", "ACCEPTED")),
            "native": dict(payload),
        }


def install_aliceblue_translator() -> AliceBlueOrderTranslator:
    from services.broker_translator_registry import register_broker_translator

    t = AliceBlueOrderTranslator()
    register_broker_translator(t)
    return t


__all__ = ["BROKER_CODE", "AliceBlueOrderTranslator", "install_aliceblue_translator"]
