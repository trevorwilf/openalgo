"""v6 Phase 6 — IIFL Capital v2 broker translator (different from IIFL/XTS)."""

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

BROKER_CODE = "iiflcapital"

_ORDER_TYPE_MAP: dict[OrderType, str] = {
    OrderType.MARKET: "MARKET",
    OrderType.LIMIT: "LIMIT",
    OrderType.STOP_LIMIT: "SL",
    OrderType.STOP: "SLM",
}

_PRODUCT_MAP: dict[str, str] = {
    "CNC": "DELIVERY",
    "NRML": "NORMAL",
    "MIS": "INTRADAY",
}

_EXCHANGE_MAP: dict[str, str] = {
    "NSE": "NSEEQ", "BSE": "BSEEQ",
    "NFO": "NSEFO", "BFO": "BSEFO",
    "CDS": "NSECURR", "BCD": "BSECURR",
    "MCX": "MCXCOMM",
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


class IIFLCapitalOrderTranslator:
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
        order_type_native = _ORDER_TYPE_MAP[order.order_type]
        out: dict[str, Any] = {
            "instrumentId": str(_ifield(instrument, "broker_token", "token") or ""),
            "exchange": _EXCHANGE_MAP.get(exchange_raw, exchange_raw),
            "transactionType": order.side.value.upper(),
            "quantity": str(int(order.quantity)),
            "orderComplexity": "REGULAR",
            "product": _native_product(order),
            "orderType": order_type_native,
            "validity": _TIF_MAP[order.time_in_force],
            "apiOrderSource": "openalgo",
        }
        if order_type_native in ("LIMIT", "SL") and order.price is not None:
            out["price"] = float(order.price)
        if order_type_native in ("SL", "SLM") and order.trigger_price is not None:
            out["triggerPrice"] = float(order.trigger_price)
        return out

    def from_native_order_response(self, payload: dict[str, Any], instrument: Any) -> dict[str, Any]:
        order_id = payload.get("orderId") or payload.get("order_id")
        if order_id is None:
            raise ValueError(f"IIFL Capital order response missing orderId: {payload!r}")
        return {
            "order_id": str(order_id),
            "status": str(payload.get("status", "ACCEPTED")),
            "native": dict(payload),
        }


def install_iiflcapital_translator() -> IIFLCapitalOrderTranslator:
    from services.broker_translator_registry import register_broker_translator

    t = IIFLCapitalOrderTranslator()
    register_broker_translator(t)
    return t


__all__ = ["BROKER_CODE", "IIFLCapitalOrderTranslator", "install_iiflcapital_translator"]
