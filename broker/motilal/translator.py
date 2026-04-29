"""v6 Phase 7 — Motilal Oswal v2 broker translator.

Note: legacy v1 path applies Market Price Protection (MPP) for MARKET
and SL-M orders because Motilal blocks those on vendor channels.
The v2 translator does NOT replicate MPP — that's operational logic
at the dispatcher level. Callers wanting MPP-protected orders should
submit LIMIT/SL with the protected price."""

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

BROKER_CODE = "motilal"

_ORDER_TYPE_MAP: dict[OrderType, str] = {
    OrderType.MARKET: "MARKET",
    OrderType.LIMIT: "LIMIT",
    OrderType.STOP_LIMIT: "STOPLOSS",
    OrderType.STOP: "STOPLOSS",
}
_PRODUCT_MAP: dict[str, str] = {
    "CNC": "DELIVERY",
    "NRML": "NORMAL",
    "MIS": "VALUEPLUS",
}
_EXCHANGE_MAP: dict[str, str] = {
    "NSE": "NSE", "BSE": "BSE",
    "NFO": "NSEFO", "BFO": "BSEFO",
    "CDS": "NSECD", "MCX": "MCX",
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


class MotilalOrderTranslator:
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
            "exchange": _EXCHANGE_MAP.get(exchange, exchange),
            "symboltoken": str(_ifield(instrument, "broker_token", "token") or ""),
            "buyorsell": order.side.value.upper(),
            "ordertype": _ORDER_TYPE_MAP[order.order_type],
            "producttype": _native_product(order),
            "orderduration": _TIF_MAP[order.time_in_force],
            "price": float(order.price) if order.price is not None else 0.0,
            "triggerprice": float(order.trigger_price) if order.trigger_price is not None else 0.0,
            "quantityinlot": int(order.quantity),
            "disclosedquantity": 0,
            "amoorder": "N",
            "algoid": "openalgo",
            "tag": order.strategy_tag or "openalgo",
            "goodtilldate": "",
            "participantcode": "",
        }

    def from_native_order_response(self, payload: dict[str, Any], instrument: Any) -> dict[str, Any]:
        # Motilal returns {"data": {"uniqueorderid": "..."}, "status": "SUCCESS"}
        data = payload.get("data") or payload
        order_id = data.get("uniqueorderid") or data.get("orderid") or data.get("order_id")
        if order_id is None:
            raise ValueError(f"Motilal order response missing uniqueorderid: {payload!r}")
        return {
            "order_id": str(order_id),
            "status": str(payload.get("status", "ACCEPTED")),
            "native": dict(payload),
        }


def install_motilal_translator() -> MotilalOrderTranslator:
    from services.broker_translator_registry import register_broker_translator

    t = MotilalOrderTranslator()
    register_broker_translator(t)
    return t


__all__ = ["BROKER_CODE", "MotilalOrderTranslator", "install_motilal_translator"]
