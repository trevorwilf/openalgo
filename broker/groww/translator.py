"""v6 Phase 6 — Groww v2 broker translator."""

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

BROKER_CODE = "groww"

_ORDER_TYPE_MAP: dict[OrderType, str] = {
    OrderType.MARKET: "MARKET",
    OrderType.LIMIT: "LIMIT",
    OrderType.STOP_LIMIT: "STOP_LOSS_LIMIT",
    OrderType.STOP: "STOP_LOSS_MARKET",
}

_PRODUCT_MAP: dict[str, str] = {"CNC": "CNC", "NRML": "NRML", "MIS": "MIS"}

_EXCHANGE_MAP: dict[str, str] = {
    "NSE": "NSE", "BSE": "BSE",
    "NFO": "NSE", "BFO": "BSE",
    "CDS": "NSE", "BCD": "BSE",
}

_SEGMENT_MAP: dict[str, str] = {
    "NSE": "CASH", "BSE": "CASH",
    "NFO": "FNO", "BFO": "FNO",
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


class GrowwOrderTranslator:
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
        exchange_raw = str(_ifield(instrument, "venue_code", "exchange") or "NSE").upper()
        out: dict[str, Any] = {
            "trading_symbol": str(_ifield(instrument, "broker_symbol", "canonical_symbol") or "X"),
            "quantity": int(order.quantity),
            "validity": _TIF_MAP[order.time_in_force],
            "exchange": _EXCHANGE_MAP.get(exchange_raw, exchange_raw),
            "segment": _SEGMENT_MAP.get(exchange_raw, "CASH"),
            "product": _native_product(order),
            "order_type": _ORDER_TYPE_MAP[order.order_type],
            "transaction_type": order.side.value.upper(),
        }
        if order.price is not None:
            out["price"] = float(order.price)
        if order.trigger_price is not None:
            out["trigger_price"] = float(order.trigger_price)
        return out

    def from_native_order_response(self, payload: dict[str, Any], instrument: Any) -> dict[str, Any]:
        # Groww returns {"groww_order_id": "...", "order_status": "..."}
        order_id = payload.get("groww_order_id") or payload.get("order_id")
        if order_id is None:
            raise ValueError(f"Groww order response missing groww_order_id: {payload!r}")
        return {
            "order_id": str(order_id),
            "status": str(payload.get("order_status") or payload.get("status", "ACCEPTED")),
            "native": dict(payload),
        }


def install_groww_translator() -> GrowwOrderTranslator:
    from services.broker_translator_registry import register_broker_translator

    t = GrowwOrderTranslator()
    register_broker_translator(t)
    return t


__all__ = ["BROKER_CODE", "GrowwOrderTranslator", "install_groww_translator"]
