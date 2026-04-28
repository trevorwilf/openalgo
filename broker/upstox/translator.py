"""v6 Phase 5 — Upstox v2 broker translator.

Bit-identical with the legacy v1 ``broker.upstox.mapping.transform_data``
shape. Native fields use Upstox's snake_case API:
``order_type`` (MARKET/LIMIT/SL/SL-M) + ``product`` (D for delivery
or carry, I for intraday) + ``transaction_type`` + ``instrument_token``.
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

BROKER_CODE = "upstox"

_ORDER_TYPE_MAP: dict[OrderType, str] = {
    OrderType.MARKET: "MARKET",
    OrderType.LIMIT: "LIMIT",
    OrderType.STOP_LIMIT: "SL",
    OrderType.STOP: "SL-M",
}

_PRODUCT_MAP: dict[str, str] = {
    "CNC": "D",   # delivery
    "NRML": "D",  # carry (overnight) — same upstox bucket
    "MIS": "I",   # intraday
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


class UpstoxOrderTranslator:
    broker_code = BROKER_CODE

    def validate(self, order: Any, instrument: Any, account_ctx: AccountContext) -> None:
        if order.order_type not in _ORDER_TYPE_MAP:
            raise UnsupportedCapability(
                broker_code=BROKER_CODE,
                capability_name="order_type",
                details=f"order_type={order.order_type.value} not supported by Upstox",
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
        instrument_token = _instrument_field(
            instrument, "broker_token", "token", "instrument_token"
        ) or ""
        return {
            "quantity": str(int(order.quantity))
            if order.quantity == order.quantity.to_integral_value()
            else str(order.quantity),
            "product": _native_product(order),
            "validity": _TIF_MAP[order.time_in_force],
            "price": str(order.price) if order.price is not None else "0",
            "tag": order.strategy_tag or "string",
            "instrument_token": str(instrument_token),
            "order_type": _ORDER_TYPE_MAP[order.order_type],
            "transaction_type": order.side.value.upper(),
            "disclosed_quantity": "0",
            "trigger_price": str(order.trigger_price) if order.trigger_price is not None else "0",
            "is_amo": "false",
        }

    def from_native_order_response(self, payload: dict[str, Any], instrument: Any) -> dict[str, Any]:
        # Upstox returns {"status": "success", "data": {"order_id": "..."}}
        data = payload.get("data") or {}
        order_id = data.get("order_id") or payload.get("order_id")
        if order_id is None:
            raise ValueError(f"Upstox order response missing order_id: {payload!r}")
        return {
            "order_id": str(order_id),
            "status": str(payload.get("status", "success")),
            "native": dict(payload),
        }


def install_upstox_translator() -> UpstoxOrderTranslator:
    from services.broker_translator_registry import register_broker_translator

    t = UpstoxOrderTranslator()
    register_broker_translator(t)
    return t


__all__ = ["BROKER_CODE", "UpstoxOrderTranslator", "install_upstox_translator"]
