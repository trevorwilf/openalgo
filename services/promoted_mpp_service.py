"""v6 Phase 5-bis — Pre-translator Market Price Protection (MPP).

Some India brokers reject MARKET / SL-M orders on vendor / algo
channels and the v1 transform_data layer compensates by fetching the
LTP and converting MARKET → LIMIT (or SL-M → SL) with a percentage
buffer (the "MPP slab"). The v2 lane preserves this behavior at the
**dispatcher level**, before the translator is invoked, so:

* Translators stay pure functions of the normalized order.
* The wire payload sent to the broker is bit-identical with the v1
  payload for users on these brokers.
* Operators can disable MPP per-broker via ``API_V2_MPP_<BROKER>=0``
  if they ever want raw MARKET orders.

Brokers requiring MARKET → LIMIT conversion (legacy v1 behavior):
flattrade, motilal, pocketful, samco, kotak, ibulls, indmoney,
shoonya, zebu.

Brokers also requiring SL-M → SL conversion (uses trigger_price, no
quote fetch needed): motilal, samco.

Quote fetch falls back to the broker's existing v1
``broker.<code>.api.data.BrokerData`` interface — no new v2 quote
adapter is required for these legacy India brokers. If the quote
fetch fails, the order passes through unchanged (degrades to whatever
the broker would return on a raw MARKET).
"""

from __future__ import annotations

import importlib
from decimal import Decimal
from typing import Any

from domain.enums import OrderType
from utils.feature_flags import is_enabled
from utils.logging import get_logger

logger = get_logger(__name__)


# Brokers whose v1 transform_data converts MARKET → LIMIT via LTP+slab.
BROKERS_REQUIRING_MPP_MARKET: frozenset[str] = frozenset(
    {
        "flattrade",
        "motilal",
        "pocketful",
        "samco",
        "kotak",
        "ibulls",
        "indmoney",
        "shoonya",
        "zebu",
    }
)

# Brokers whose v1 transform_data also converts SL-M → SL via trigger+slab.
BROKERS_REQUIRING_MPP_SLM: frozenset[str] = frozenset(
    {
        "motilal",
        "samco",
    }
)


def requires_mpp_market(broker_code: str) -> bool:
    """True iff the broker needs MARKET → LIMIT MPP conversion."""
    return (broker_code or "").lower() in BROKERS_REQUIRING_MPP_MARKET


def requires_mpp_slm(broker_code: str) -> bool:
    """True iff the broker needs SL-M → SL MPP conversion."""
    return (broker_code or "").lower() in BROKERS_REQUIRING_MPP_SLM


def _instrument_attr(instrument: Any, *attrs: str) -> Any:
    if instrument is None:
        return None
    for a in attrs:
        v = getattr(instrument, a, None)
        if v:
            return v
    return None


def _operator_disable_flag(broker_code: str) -> bool:
    """Operator escape hatch: ``API_V2_MPP_<BROKER>=0`` disables MPP."""
    name = f"API_V2_MPP_{broker_code.upper()}"
    return is_enabled(name, default=True) is False


def _fetch_ltp_and_tick(
    broker_code: str,
    symbol: str,
    venue: str,
    auth_token: str,
) -> tuple[float | None, float | None]:
    """Fetch LTP + tick_size from the broker's v1 BrokerData class.

    Returns ``(None, None)`` on any error so the dispatcher can pass
    the order through unchanged.
    """
    try:
        mod = importlib.import_module(f"broker.{broker_code.lower()}.api.data")
    except ImportError as e:
        logger.warning("MPP: broker.%s.api.data missing: %s", broker_code, e)
        return None, None

    broker_data_cls = getattr(mod, "BrokerData", None)
    if broker_data_cls is None:
        logger.warning("MPP: broker.%s.api.data has no BrokerData class", broker_code)
        return None, None

    try:
        # Most India broker BrokerData classes accept a single auth_token
        # arg. ibulls and a couple of others take (auth, feed) pairs;
        # try the single-arg form first and fall through.
        try:
            broker_data = broker_data_cls(auth_token)
        except TypeError:
            broker_data = broker_data_cls(auth_token, auth_token)

        quote = broker_data.get_quotes(symbol, venue)
        if not isinstance(quote, dict):
            return None, None
        ltp_raw = quote.get("ltp")
        tick_raw = quote.get("tick_size")
        ltp = float(ltp_raw) if ltp_raw is not None else None
        tick = float(tick_raw) if tick_raw is not None else None
        return ltp, tick
    except Exception as e:  # broker quote API can fail for many reasons
        logger.warning("MPP: quote fetch failed for %s/%s on %s: %s", symbol, venue, broker_code, e)
        return None, None


def _calculate_protected_price(
    base_price: float,
    side: str,
    symbol: str,
    tick_size: float | None,
) -> float:
    """Wrap :func:`utils.mpp_slab.calculate_protected_price`."""
    from utils.mpp_slab import calculate_protected_price, get_instrument_type_from_symbol

    instrument_type = get_instrument_type_from_symbol(symbol or "")
    return calculate_protected_price(
        price=base_price,
        action=side,
        symbol=symbol,
        instrument_type=instrument_type,
        tick_size=tick_size,
    )


def apply_mpp_if_required(
    order: Any,
    broker_code: str,
    instrument: Any,
    auth_token: str | None = None,
) -> Any:
    """Apply MPP to ``order`` if ``broker_code`` requires it.

    Returns either the original ``order`` (no change) or a
    ``model_copy`` with order_type / price replaced.

    No-ops for any broker not in
    :data:`BROKERS_REQUIRING_MPP_MARKET` /
    :data:`BROKERS_REQUIRING_MPP_SLM`. Also no-ops when:

    * the operator has disabled MPP via ``API_V2_MPP_<BROKER>=0``
    * ``auth_token`` is missing (cannot fetch quote)
    * the order is not MARKET (or STOP, for SL-M brokers)
    * the quote fetch fails or returns ltp <= 0
    """
    if order is None:
        return order
    bc = (broker_code or "").lower()
    if not bc:
        return order
    if _operator_disable_flag(bc):
        logger.debug("MPP: disabled by operator for %s", bc)
        return order

    side = order.side.value.upper()
    symbol = _instrument_attr(instrument, "broker_symbol", "canonical_symbol", "symbol") or ""
    venue = _instrument_attr(instrument, "venue_code", "exchange", "brexchange") or ""

    # MARKET → LIMIT
    if order.order_type == OrderType.MARKET and bc in BROKERS_REQUIRING_MPP_MARKET:
        if not auth_token:
            logger.debug("MPP: skip (no auth_token) for %s MARKET", bc)
            return order
        ltp, tick_size = _fetch_ltp_and_tick(bc, str(symbol), str(venue), auth_token)
        if ltp is None or ltp <= 0:
            return order
        protected = _calculate_protected_price(ltp, side, str(symbol), tick_size)
        if protected <= 0:
            return order
        logger.info(
            "MPP: %s MARKET → LIMIT @ %s (ltp=%s side=%s)",
            bc, protected, ltp, side,
        )
        return order.model_copy(update={
            "order_type": OrderType.LIMIT,
            "price": Decimal(str(protected)),
        })

    # SL-M → SL (uses trigger_price, no quote fetch)
    if order.order_type == OrderType.STOP and bc in BROKERS_REQUIRING_MPP_SLM:
        if order.trigger_price is None:
            return order
        trigger = float(order.trigger_price)
        if trigger <= 0:
            return order
        protected = _calculate_protected_price(trigger, side, str(symbol), None)
        if protected <= 0:
            return order
        logger.info(
            "MPP: %s STOP → STOP_LIMIT @ %s (trigger=%s side=%s)",
            bc, protected, trigger, side,
        )
        return order.model_copy(update={
            "order_type": OrderType.STOP_LIMIT,
            "price": Decimal(str(protected)),
        })

    return order


__all__ = [
    "BROKERS_REQUIRING_MPP_MARKET",
    "BROKERS_REQUIRING_MPP_SLM",
    "apply_mpp_if_required",
    "requires_mpp_market",
    "requires_mpp_slm",
]
