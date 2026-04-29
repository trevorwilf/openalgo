"""Shared XTS-family v2 broker translator base.

The Symphony Fintech XTS API is the basis for compositedge, fivepaisaxts,
ibulls, iifl, jainamxts, and wisdom. They share the same native shape
(exchangeSegment + exchangeInstrumentID + productType + orderType +
orderSide + timeInForce + orderQuantity + limitPrice + stopPrice +
orderUniqueIdentifier).

Per-broker translators subclass :class:`XTSFamilyOrderTranslator` and
override ``broker_code`` only. Bit-identical with the legacy v1
``broker.<broker>.mapping.transform_data`` shape for every input the
v1 lane currently accepts.
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

_ORDER_TYPE_MAP: dict[OrderType, str] = {
    OrderType.MARKET: "MARKET",
    OrderType.LIMIT: "LIMIT",
    OrderType.STOP_LIMIT: "STOPLIMIT",
    OrderType.STOP: "STOPMARKET",
}

_PRODUCT_MAP: dict[str, str] = {
    "CNC": "CNC",
    "NRML": "NRML",
    "MIS": "MIS",
}

_EXCHANGE_SEGMENT_MAP: dict[str, str] = {
    "NSE": "NSECM",
    "BSE": "BSECM",
    "MCX": "MCXFO",
    "NFO": "NSEFO",
    "BFO": "BSEFO",
    "CDS": "NSECD",
    "BCD": "BSECD",
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


class XTSFamilyOrderTranslator:
    """Base translator for XTS-family brokers (compositedge, fivepaisaxts,
    ibulls, iifl, jainamxts, wisdom).

    Subclasses override ``broker_code`` only.
    """

    broker_code: str = "_xts_family"

    def validate(self, order: Any, instrument: Any, account_ctx: AccountContext) -> None:
        if order.order_type not in _ORDER_TYPE_MAP:
            raise UnsupportedCapability(
                broker_code=self.broker_code,
                capability_name="order_type",
                details=f"order_type={order.order_type.value} not supported",
                dimension="order_type",
            )
        if order.time_in_force not in _TIF_MAP:
            raise UnsupportedCapability(
                broker_code=self.broker_code,
                capability_name="time_in_force",
                details=f"time_in_force={order.time_in_force.value} not supported",
                dimension="tif",
            )
        if order.session not in _SUPPORTED_SESSIONS:
            raise UnsupportedCapability(
                broker_code=self.broker_code,
                capability_name="session",
                details=f"session={order.session.value} not supported",
                dimension="session",
            )
        if order.quantity_unit not in _SUPPORTED_QUANTITY_UNITS:
            raise UnsupportedCapability(
                broker_code=self.broker_code,
                capability_name="quantity_unit",
                details=f"quantity_unit={order.quantity_unit.value} not supported",
                dimension="quantity_unit",
            )

    def to_native(self, order: Any, instrument: Any, account_ctx: AccountContext) -> dict[str, Any]:
        self.validate(order, instrument, account_ctx)
        instrument_id = _instrument_field(
            instrument, "broker_token", "token", "exchangeInstrumentID"
        ) or ""
        exchange = str(
            _instrument_field(instrument, "venue_code", "exchange", "brexchange") or "NSE"
        ).upper()
        return {
            "exchangeSegment": _EXCHANGE_SEGMENT_MAP.get(exchange, exchange),
            "exchangeInstrumentID": instrument_id,
            "productType": _native_product(order),
            "orderType": _ORDER_TYPE_MAP[order.order_type],
            "orderSide": order.side.value.upper(),
            "timeInForce": _TIF_MAP[order.time_in_force],
            "disclosedQuantity": "0",
            "orderQuantity": str(int(order.quantity))
            if order.quantity == order.quantity.to_integral_value()
            else str(order.quantity),
            "limitPrice": str(order.price) if order.price is not None else "0",
            "stopPrice": str(order.trigger_price) if order.trigger_price is not None else "0",
            "orderUniqueIdentifier": order.strategy_tag or "openalgo",
        }

    def from_native_order_response(self, payload: dict[str, Any], instrument: Any) -> dict[str, Any]:
        # XTS responses: {"result": {"AppOrderID": "..."}, "type": "success"}
        result = payload.get("result") or {}
        order_id = (
            result.get("AppOrderID")
            or result.get("OrderUniqueIdentifier")
            or payload.get("AppOrderID")
            or payload.get("order_id")
        )
        if order_id is None:
            raise ValueError(f"XTS order response missing AppOrderID: {payload!r}")
        return {
            "order_id": str(order_id),
            "status": str(payload.get("type", "ACCEPTED")),
            "native": dict(payload),
        }


__all__ = ["XTSFamilyOrderTranslator"]
