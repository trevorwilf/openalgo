"""v6 Phase 6 — 5paisa (legacy) v2 broker translator.

Different from 5paisaXTS — this is the older 5paisa native API
which uses single-letter exchange codes (N/B/M) and ScripCode."""

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

BROKER_CODE = "fivepaisa"

_SIDE_MAP: dict[OrderSide, str] = {OrderSide.BUY: "B", OrderSide.SELL: "S"}

_EXCHANGE_MAP: dict[str, str] = {
    "NSE": "N", "BSE": "B", "NFO": "N", "BFO": "B",
    "CDS": "N", "BCD": "B", "MCX": "M",
    "NSE_INDEX": "N", "BSE_INDEX": "B",
}

_EXCHANGE_TYPE_MAP: dict[str, str] = {
    "NSE": "C", "BSE": "C", "NFO": "D", "BFO": "D",
    "CDS": "U", "BCD": "U", "MCX": "D",
}

_TIF_MAP: dict[TimeInForce, str] = {TimeInForce.DAY: "DAY", TimeInForce.IOC: "IOC"}
_SUPPORTED_ORDER_TYPES = frozenset({OrderType.MARKET, OrderType.LIMIT, OrderType.STOP, OrderType.STOP_LIMIT})
_SUPPORTED_QUANTITY_UNITS = frozenset({QuantityUnit.WHOLE, QuantityUnit.LOTS})
_SUPPORTED_SESSIONS = frozenset({Session.REGULAR})


def _is_intraday(order: Any) -> bool:
    if order.position_effect == PositionEffect.REDUCE_ONLY:
        return True
    hint = (order.extra or {}).get("legacy_product_hint")
    return isinstance(hint, str) and hint.upper() == "MIS"


def _ifield(instrument: Any, *attrs: str) -> Any:
    for a in attrs:
        v = getattr(instrument, a, None)
        if v:
            return v
    return None


class FivePaisaOrderTranslator:
    broker_code = BROKER_CODE

    def validate(self, order: Any, instrument: Any, account_ctx: AccountContext) -> None:
        if order.order_type not in _SUPPORTED_ORDER_TYPES:
            raise UnsupportedCapability(broker_code=BROKER_CODE, capability_name="order_type", dimension="order_type")
        if order.time_in_force not in _TIF_MAP:
            raise UnsupportedCapability(broker_code=BROKER_CODE, capability_name="tif", dimension="tif")
        if order.session not in _SUPPORTED_SESSIONS:
            raise UnsupportedCapability(broker_code=BROKER_CODE, capability_name="session", dimension="session")
        if order.quantity_unit not in _SUPPORTED_QUANTITY_UNITS:
            raise UnsupportedCapability(broker_code=BROKER_CODE, capability_name="quantity_unit", dimension="quantity_unit")
        if order.side not in _SIDE_MAP:
            raise UnsupportedCapability(broker_code=BROKER_CODE, capability_name="side")

    def to_native(self, order: Any, instrument: Any, account_ctx: AccountContext) -> dict[str, Any]:
        self.validate(order, instrument, account_ctx)
        exchange = str(_ifield(instrument, "venue_code", "exchange") or "NSE").upper()
        return {
            "OrderType": _SIDE_MAP[order.side],
            "Exchange": _EXCHANGE_MAP.get(exchange, "N"),
            "ExchangeType": _EXCHANGE_TYPE_MAP.get(exchange, "C"),
            "ScripCode": str(_ifield(instrument, "broker_token", "token") or ""),
            "Price": float(order.price) if order.price is not None else 0.0,
            "Qty": int(order.quantity),
            "StopLossPrice": float(order.trigger_price) if order.trigger_price is not None else 0.0,
            "DisQty": 0,
            "IsIntraday": _is_intraday(order),
            "AHPlaced": "N",
            "RemoteOrderID": order.strategy_tag or "OpenAlgo",
        }

    def from_native_order_response(self, payload: dict[str, Any], instrument: Any) -> dict[str, Any]:
        # 5paisa returns body with {"head": ..., "body": {"BrokerOrderID": "..."}} or similar.
        body = payload.get("body") or payload
        order_id = body.get("BrokerOrderID") or body.get("ExchOrderID") or body.get("order_id")
        if order_id is None:
            raise ValueError(f"5paisa order response missing order id: {payload!r}")
        return {
            "order_id": str(order_id),
            "status": str(body.get("Status") or body.get("status", "ACCEPTED")),
            "native": dict(payload),
        }


def install_fivepaisa_translator() -> FivePaisaOrderTranslator:
    from services.broker_translator_registry import register_broker_translator

    t = FivePaisaOrderTranslator()
    register_broker_translator(t)
    return t


__all__ = ["BROKER_CODE", "FivePaisaOrderTranslator", "install_fivepaisa_translator"]
