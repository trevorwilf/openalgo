"""v6 Phase 5 — Fyers v2 broker translator.

Bit-identical with the legacy v1 ``broker.fyers.mapping.transform_data``
shape. Native fields use Fyers's numeric/string mix:
``type`` (1=LIMIT, 2=MARKET, 3=SL-M, 4=SL) + ``side`` (1=BUY, -1=SELL) +
``productType`` (CNC/MARGIN/INTRADAY) + ``symbol`` (broker symbol) +
``limitPrice`` / ``stopPrice``.
"""

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

BROKER_CODE = "fyers"

_ORDER_TYPE_MAP: dict[OrderType, int] = {
    OrderType.MARKET: 2,
    OrderType.LIMIT: 1,
    OrderType.STOP_LIMIT: 4,   # SL (stop-loss limit)
    OrderType.STOP: 3,         # SL-M (stop-loss market)
}

_SIDE_MAP: dict[OrderSide, int] = {
    OrderSide.BUY: 1,
    OrderSide.SELL: -1,
}

_PRODUCT_MAP: dict[str, str] = {
    "CNC": "CNC",
    "NRML": "MARGIN",
    "MIS": "INTRADAY",
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


class FyersOrderTranslator:
    broker_code = BROKER_CODE

    def validate(self, order: Any, instrument: Any, account_ctx: AccountContext) -> None:
        if order.order_type not in _ORDER_TYPE_MAP:
            raise UnsupportedCapability(
                broker_code=BROKER_CODE,
                capability_name="order_type",
                details=f"order_type={order.order_type.value} not supported by Fyers",
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
        if order.side not in _SIDE_MAP:
            raise UnsupportedCapability(
                broker_code=BROKER_CODE,
                capability_name="side",
                details=f"side={order.side.value} not supported",
            )

    def to_native(self, order: Any, instrument: Any, account_ctx: AccountContext) -> dict[str, Any]:
        self.validate(order, instrument, account_ctx)
        symbol = _instrument_field(
            instrument, "broker_symbol", "brsymbol", "canonical_symbol", "symbol"
        ) or "X"
        return {
            "symbol": str(symbol),
            "qty": int(order.quantity),
            "type": _ORDER_TYPE_MAP[order.order_type],
            "side": _SIDE_MAP[order.side],
            "productType": _native_product(order),
            "limitPrice": float(order.price) if order.price is not None else 0.0,
            "stopPrice": float(order.trigger_price) if order.trigger_price is not None else 0.0,
            "validity": _TIF_MAP[order.time_in_force],
            "disclosedQty": 0,
            "offlineOrder": False,
            "stopLoss": 0,
            "takeProfit": 0,
            "orderTag": order.strategy_tag or "openalgo",
        }

    def from_native_order_response(self, payload: dict[str, Any], instrument: Any) -> dict[str, Any]:
        # Fyers returns {"s": "ok", "id": "..."} or under "data"
        data = payload.get("data") or payload
        order_id = data.get("id") or data.get("orderId") or data.get("order_id")
        if order_id is None:
            raise ValueError(f"Fyers order response missing id: {payload!r}")
        return {
            "order_id": str(order_id),
            "status": "ACCEPTED" if payload.get("s", "ok") == "ok" else "REJECTED",
            "native": dict(payload),
        }


def install_fyers_translator() -> FyersOrderTranslator:
    from services.broker_translator_registry import register_broker_translator

    t = FyersOrderTranslator()
    register_broker_translator(t)
    return t


__all__ = ["BROKER_CODE", "FyersOrderTranslator", "install_fyers_translator"]
