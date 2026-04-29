"""v6 Phase 7 — Shoonya (Finvasia/Noren) v2 broker translator."""

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

BROKER_CODE = "shoonya"

_PRICE_TYPE_MAP: dict[OrderType, str] = {
    OrderType.MARKET: "MKT",
    OrderType.LIMIT: "LMT",
    OrderType.STOP_LIMIT: "SL-LMT",
    OrderType.STOP: "SL-MKT",
}
_PRODUCT_MAP: dict[str, str] = {"CNC": "C", "NRML": "M", "MIS": "I"}
_SIDE_MAP: dict[OrderSide, str] = {OrderSide.BUY: "B", OrderSide.SELL: "S"}
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


class ShoonyaOrderTranslator:
    broker_code = BROKER_CODE

    def validate(self, order: Any, instrument: Any, account_ctx: AccountContext) -> None:
        if order.order_type not in _PRICE_TYPE_MAP:
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
            "uid": str(account_ctx.account_id),
            "actid": str(account_ctx.account_id),
            "exch": str(_ifield(instrument, "venue_code", "exchange") or "NSE").upper(),
            "tsym": str(_ifield(instrument, "broker_symbol", "canonical_symbol") or "X"),
            "qty": str(int(order.quantity)),
            "prc": str(order.price) if order.price is not None else "0",
            "trgprc": str(order.trigger_price) if order.trigger_price is not None else "0",
            "trantype": _SIDE_MAP[order.side],
            "prd": _native_product(order),
            "prctyp": _PRICE_TYPE_MAP[order.order_type],
            "ret": _TIF_MAP[order.time_in_force],
            "remarks": order.strategy_tag or "openalgo",
        }

    def from_native_order_response(self, payload: dict[str, Any], instrument: Any) -> dict[str, Any]:
        order_id = payload.get("norenordno") or payload.get("orderid") or payload.get("order_id")
        if order_id is None:
            raise ValueError(f"Shoonya order response missing norenordno: {payload!r}")
        return {
            "order_id": str(order_id),
            "status": str(payload.get("stat") or payload.get("status", "Ok")),
            "native": dict(payload),
        }


def install_shoonya_translator() -> ShoonyaOrderTranslator:
    from services.broker_translator_registry import register_broker_translator

    t = ShoonyaOrderTranslator()
    register_broker_translator(t)
    return t


__all__ = ["BROKER_CODE", "ShoonyaOrderTranslator", "install_shoonya_translator"]
