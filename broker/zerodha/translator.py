"""v6 Phase 5 — Zerodha v2 broker translator.

Implements :class:`BrokerOrderTranslator` for Zerodha (Kite Connect).
Translates :class:`NormalizedOrderRequest` to Zerodha's native order
shape used by ``broker.zerodha.api.order_api`` and reverses the
broker-native order-creation response.

Behavior parity with the legacy v1 path is **bit-identical for India
inputs**: every domain-enum value the v1 lane currently accepts maps
to the same Kite-native string the v1 transformer emits. The
translator enforces fail-closed semantics for any v2-only feature
Zerodha cannot honor (US extended hours, fractional shares, etc.).

Registered into :mod:`services.broker_translator_registry` via
:func:`install_zerodha_translator`. The promoted ``/api/v2/orders``
dispatcher selects this translator when ``API_V2_ZERODHA=1`` and
the active broker is Zerodha.
"""

from __future__ import annotations

from typing import Any

from domain.account_context import AccountContext
from domain.broker_translator import BrokerOrderTranslator  # noqa: F401 — Protocol re-export
from domain.enums import (
    OrderSide,
    OrderType,
    PositionEffect,
    QuantityUnit,
    Session,
    TimeInForce,
)
from domain.errors import UnsupportedCapability

BROKER_CODE = "zerodha"

# Domain OrderType → Kite order_type. India v1 used MARKET / LIMIT /
# SL / SL-M; SL is stop-loss LIMIT, SL-M is stop-loss MARKET.
_ORDER_TYPE_MAP: dict[OrderType, str] = {
    OrderType.MARKET: "MARKET",
    OrderType.LIMIT: "LIMIT",
    OrderType.STOP_LIMIT: "SL",   # India SL = stop-loss LIMIT
    OrderType.STOP: "SL-M",       # India SL-M = stop-loss MARKET
}

# Domain TimeInForce → Kite validity. Zerodha exposes DAY + IOC; FOK
# is rejected by Kite for retail equity (it's accepted on derivatives
# in some flows but the v1 lane never used it, so we stay strict).
_TIF_MAP: dict[TimeInForce, str] = {
    TimeInForce.DAY: "DAY",
    TimeInForce.IOC: "IOC",
}

# Quantity units Zerodha accepts. India trades in WHOLE shares for
# equity and LOTS for F&O (the lot-size translation happens upstream
# in the OpenAlgo lot-aware path; the translator just emits the
# integer quantity).
_SUPPORTED_QUANTITY_UNITS: frozenset[QuantityUnit] = frozenset(
    {QuantityUnit.WHOLE, QuantityUnit.LOTS}
)

_SUPPORTED_SESSIONS: frozenset[Session] = frozenset({Session.REGULAR})


def _native_product_for(order: Any, instrument: Any) -> str:
    """Map (NormalizedOrderRequest, instrument) → CNC / NRML / MIS.

    Behavior is bit-identical with
    ``domain.translators.normalized_order_to_legacy_fields``:

    * ``position_effect=REDUCE_ONLY`` → MIS (intraday).
    * Otherwise: caller may pin via ``order.extra["legacy_product_hint"]``
      (the v1 path forwards the original product string here so v2
      gives the same answer); default fallback is CNC.

    A future Phase 5-bis enriches this with venue-aware F&O
    auto-detection (NFO/BFO/MCX → NRML default) once instrument
    resolution carries asset_class through the v2 pipeline.
    """
    if order.position_effect == PositionEffect.REDUCE_ONLY:
        return "MIS"
    hint = order.extra.get("legacy_product_hint") if order.extra else None
    if isinstance(hint, str) and hint.upper() in ("CNC", "NRML", "MIS"):
        return hint.upper()
    return "CNC"


def _instrument_tradingsymbol(instrument: Any) -> str:
    """Resolve the Kite tradingsymbol from a resolved instrument.

    Accepts either a :class:`ResolvedInstrument`-like object with
    ``broker_symbol`` / ``canonical_symbol`` attributes or a
    legacy SymToken-like row with ``brsymbol`` / ``symbol``.
    Falls back to ``canonical_symbol`` when broker-specific symbol
    is not populated.
    """
    for attr in ("broker_symbol", "brsymbol", "tradingsymbol"):
        v = getattr(instrument, attr, None)
        if v:
            return str(v)
    for attr in ("canonical_symbol", "symbol"):
        v = getattr(instrument, attr, None)
        if v:
            return str(v)
    raise ValueError(
        f"cannot resolve Kite tradingsymbol from instrument {instrument!r}"
    )


def _instrument_exchange(instrument: Any) -> str:
    """Resolve the Kite exchange code from a resolved instrument."""
    for attr in ("venue_code", "exchange", "brexchange"):
        v = getattr(instrument, attr, None)
        if v:
            return str(v).upper()
    raise ValueError(
        f"cannot resolve Kite exchange from instrument {instrument!r}"
    )


class ZerodhaOrderTranslator:
    """Zerodha (Kite Connect) v2 order translator."""

    broker_code = BROKER_CODE

    def validate(
        self,
        order: Any,
        instrument: Any,
        account_ctx: AccountContext,
    ) -> None:
        if order.order_type not in _ORDER_TYPE_MAP:
            raise UnsupportedCapability(
                broker_code=BROKER_CODE,
                capability_name="order_type",
                details=(
                    f"order_type={order.order_type.value} not supported by "
                    "Zerodha; supported: MARKET, LIMIT, STOP, STOP_LIMIT"
                ),
                dimension="order_type",
            )

        if order.time_in_force not in _TIF_MAP:
            raise UnsupportedCapability(
                broker_code=BROKER_CODE,
                capability_name="time_in_force",
                details=(
                    f"time_in_force={order.time_in_force.value} not supported "
                    "by Zerodha; supported: DAY, IOC"
                ),
                dimension="tif",
            )

        if order.session not in _SUPPORTED_SESSIONS:
            raise UnsupportedCapability(
                broker_code=BROKER_CODE,
                capability_name="session",
                details=(
                    f"session={order.session.value} not supported by Zerodha; "
                    "Indian markets have no extended-hours concept"
                ),
                dimension="session",
            )

        if order.quantity_unit not in _SUPPORTED_QUANTITY_UNITS:
            raise UnsupportedCapability(
                broker_code=BROKER_CODE,
                capability_name="quantity_unit",
                details=(
                    f"quantity_unit={order.quantity_unit.value} not supported "
                    "by Zerodha; supported: WHOLE, LOTS"
                ),
                dimension="quantity_unit",
            )

    def to_native(
        self,
        order: Any,
        instrument: Any,
        account_ctx: AccountContext,
    ) -> dict[str, Any]:
        """Build the Kite Connect order request body.

        Bit-identical to ``broker.zerodha.mapping.transform_data.transform_data``
        for any input that round-trips through legacy v1 first.
        """
        # Re-validate so to_native is safe to call directly in tests
        # without the dispatcher having called validate first.
        self.validate(order, instrument, account_ctx)

        return {
            "tradingsymbol": _instrument_tradingsymbol(instrument),
            "exchange": _instrument_exchange(instrument),
            "transaction_type": order.side.value.upper(),
            "order_type": _ORDER_TYPE_MAP[order.order_type],
            "quantity": str(int(order.quantity))
            if order.quantity == order.quantity.to_integral_value()
            else str(order.quantity),
            "product": _native_product_for(order, instrument),
            "price": str(order.price) if order.price is not None else "0",
            "trigger_price": str(order.trigger_price)
            if order.trigger_price is not None
            else "0",
            "disclosed_quantity": "0",
            "validity": _TIF_MAP[order.time_in_force],
            "market_protection": "-1",
            "tag": order.strategy_tag or "openalgo",
        }

    def from_native_order_response(
        self,
        payload: dict[str, Any],
        instrument: Any,
    ) -> dict[str, Any]:
        """Map Kite's order-creation response to OpenAlgo's normalized
        envelope.

        Kite returns ``{"order_id": "<id>", "status": "success"}`` on
        accept. We surface ``order_id`` and ``status`` plus the raw
        payload under ``native``.
        """
        order_id = payload.get("order_id") or payload.get("orderId")
        if order_id is None:
            raise ValueError(
                f"Zerodha order response missing order_id: {payload!r}"
            )
        return {
            "order_id": str(order_id),
            "status": str(payload.get("status", "ACCEPTED")),
            "native": dict(payload),
        }


def install_zerodha_translator() -> ZerodhaOrderTranslator:
    """Register the Zerodha translator into the broker_translator_registry."""
    from services.broker_translator_registry import register_broker_translator

    t = ZerodhaOrderTranslator()
    register_broker_translator(t)
    return t


__all__ = [
    "BROKER_CODE",
    "ZerodhaOrderTranslator",
    "install_zerodha_translator",
]
