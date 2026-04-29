"""v6 Phase 6 — IndMoney v2 broker translator."""

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

BROKER_CODE = "indmoney"

_ORDER_TYPE_MAP: dict[OrderType, str] = {
    OrderType.MARKET: "MARKET",
    OrderType.LIMIT: "LIMIT",
    OrderType.STOP_LIMIT: "LIMIT",   # IndMoney maps SL → LIMIT (legacy v1 quirk)
    OrderType.STOP: "MARKET",        # SL-M → MARKET
}

_PRODUCT_MAP: dict[str, str] = {
    "CNC": "CNC",
    "NRML": "MARGIN",
    "MIS": "INTRADAY",
}

_SEGMENT_MAP: dict[str, str] = {
    "NSE": "EQUITY", "BSE": "EQUITY",
    "NFO": "DERIVATIVE", "BFO": "DERIVATIVE",
    "CDS": "DERIVATIVE", "BCD": "DERIVATIVE",
}

_EXCHANGE_MAP: dict[str, str] = {
    "NSE": "NSE", "BSE": "BSE",
    "NFO": "NSE", "BFO": "BSE",
    "CDS": "NSE", "BCD": "BSE",
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


class IndMoneyOrderTranslator:
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
            "txn_type": order.side.value.upper(),
            "exchange": _EXCHANGE_MAP.get(exchange_raw, exchange_raw),
            "segment": _SEGMENT_MAP.get(exchange_raw, "EQUITY"),
            "product": _native_product(order),
            "order_type": _ORDER_TYPE_MAP[order.order_type],
            "validity": _TIF_MAP[order.time_in_force],
            "security_id": str(_ifield(instrument, "broker_token", "token") or ""),
            "qty": int(order.quantity),
            "is_amo": False,
        }
        if order.order_type in (OrderType.LIMIT, OrderType.STOP_LIMIT) and order.price is not None:
            out["limit_price"] = float(order.price)
        return out

    def from_native_order_response(self, payload: dict[str, Any], instrument: Any) -> dict[str, Any]:
        order_id = payload.get("orderId") or payload.get("order_id") or payload.get("orderid")
        if order_id is None:
            raise ValueError(f"IndMoney order response missing orderId: {payload!r}")
        return {
            "order_id": str(order_id),
            "status": str(payload.get("status", "ACCEPTED")),
            "native": dict(payload),
        }


def install_indmoney_translator() -> IndMoneyOrderTranslator:
    from services.broker_translator_registry import register_broker_translator

    t = IndMoneyOrderTranslator()
    register_broker_translator(t)
    return t


__all__ = ["BROKER_CODE", "IndMoneyOrderTranslator", "install_indmoney_translator"]
