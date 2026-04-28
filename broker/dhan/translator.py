"""v6 Phase 5 — Dhan v2 broker translator.

Bit-identical with the legacy v1 ``broker.dhan.mapping.transform_data``
shape. Native fields use Dhan's camelCase v2 API:
``transactionType`` + ``exchangeSegment`` (NSE_EQ/etc.) +
``productType`` (CNC/MARGIN/INTRADAY) + ``orderType``
(MARKET/LIMIT/STOP_LOSS/STOP_LOSS_MARKET) + ``securityId``.
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

BROKER_CODE = "dhan"

_ORDER_TYPE_MAP: dict[OrderType, str] = {
    OrderType.MARKET: "MARKET",
    OrderType.LIMIT: "LIMIT",
    OrderType.STOP_LIMIT: "STOP_LOSS",
    OrderType.STOP: "STOP_LOSS_MARKET",
}

_PRODUCT_MAP: dict[str, str] = {
    "CNC": "CNC",
    "NRML": "MARGIN",
    "MIS": "INTRADAY",
}

_EXCHANGE_SEGMENT_MAP: dict[str, str] = {
    "NSE": "NSE_EQ",
    "BSE": "BSE_EQ",
    "CDS": "NSE_CURRENCY",
    "NFO": "NSE_FNO",
    "BFO": "BSE_FNO",
    "BCD": "BSE_CURRENCY",
    "MCX": "MCX_COMM",
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


class DhanOrderTranslator:
    broker_code = BROKER_CODE

    def validate(self, order: Any, instrument: Any, account_ctx: AccountContext) -> None:
        if order.order_type not in _ORDER_TYPE_MAP:
            raise UnsupportedCapability(
                broker_code=BROKER_CODE,
                capability_name="order_type",
                details=f"order_type={order.order_type.value} not supported by Dhan",
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
        security_id = _instrument_field(instrument, "broker_token", "token", "securityId") or ""
        exchange_raw = str(
            _instrument_field(instrument, "venue_code", "exchange", "brexchange") or "NSE"
        ).upper()
        exchange_segment = _EXCHANGE_SEGMENT_MAP.get(exchange_raw, exchange_raw)

        out: dict[str, Any] = {
            "dhanClientId": str(account_ctx.account_id),
            "transactionType": order.side.value.upper(),
            "exchangeSegment": exchange_segment,
            "productType": _native_product(order),
            "orderType": _ORDER_TYPE_MAP[order.order_type],
            "validity": _TIF_MAP[order.time_in_force],
            "securityId": str(security_id),
            "quantity": int(order.quantity),
        }
        if order.order_type != OrderType.MARKET and order.price is not None:
            out["price"] = float(order.price)
        if order.order_type in (OrderType.STOP, OrderType.STOP_LIMIT):
            if order.trigger_price is None:
                raise ValueError("Trigger price required for stop orders")
            out["triggerPrice"] = float(order.trigger_price)
        return out

    def from_native_order_response(self, payload: dict[str, Any], instrument: Any) -> dict[str, Any]:
        order_id = payload.get("orderId") or payload.get("order_id")
        if order_id is None:
            raise ValueError(f"Dhan order response missing orderId: {payload!r}")
        status = payload.get("orderStatus") or payload.get("status", "ACCEPTED")
        return {
            "order_id": str(order_id),
            "status": str(status),
            "native": dict(payload),
        }


def install_dhan_translator() -> DhanOrderTranslator:
    from services.broker_translator_registry import register_broker_translator

    t = DhanOrderTranslator()
    register_broker_translator(t)
    return t


__all__ = ["BROKER_CODE", "DhanOrderTranslator", "install_dhan_translator"]
