"""Bridges between legacy Indian-shaped strings and normalized domain types.

Two-way where possible:

- `legacy_* -> *` (Indian strings into domain types) is **lossless** for
  every currently valid input.
- `normalized_* -> legacy_*` is best-effort and raises
  `UnsupportedCapability` for concepts the legacy shape cannot express
  (e.g., `MARKET_ON_OPEN` has no Indian representation today).

The legacy vocabulary lives in `utils/constants.py`. Per Phase 0
invariant 5, **new code may not import VALID_EXCHANGES / VALID_PRODUCT_TYPES
/ VALID_PRICE_TYPES**. Translators here are the sanctioned bridge.
"""

from __future__ import annotations

from typing import Any

from domain.enums import (
    MarketFamily,
    OrderType,
    PositionEffect,
    Session,
    TimeInForce,
)
from domain.errors import UnsupportedCapability

# Legacy Indian exchange codes (from utils/constants.py:48). Duplicated
# intentionally so domain/ imports nothing from utils.constants.
_LEGACY_INDIAN_EXCHANGES: frozenset[str] = frozenset(
    {
        "NSE",
        "NFO",
        "CDS",
        "BSE",
        "BFO",
        "BCD",
        "MCX",
        "NCDEX",
        "NSE_INDEX",
        "BSE_INDEX",
    }
)

_LEGACY_CRYPTO_EXCHANGES: frozenset[str] = frozenset({"CRYPTO"})

_ALL_LEGACY_EXCHANGES: frozenset[str] = _LEGACY_INDIAN_EXCHANGES | _LEGACY_CRYPTO_EXCHANGES

_LEGACY_PRODUCTS: frozenset[str] = frozenset({"CNC", "NRML", "MIS"})
_LEGACY_PRICETYPES: frozenset[str] = frozenset({"MARKET", "LIMIT", "SL", "SL-M"})


def legacy_exchange_to_venue_code(ex: str) -> str:
    """Uppercase + validate. Venue-code semantics are Phase 2 territory;
    here we only assert the string is a known legacy value.
    """
    if not isinstance(ex, str):
        raise ValueError(f"legacy_exchange_to_venue_code expects str, got {type(ex).__name__}")
    code = ex.strip().upper()
    if code not in _ALL_LEGACY_EXCHANGES:
        raise ValueError(
            f"Unknown legacy exchange {ex!r}. Known: "
            f"{', '.join(sorted(_ALL_LEGACY_EXCHANGES))}"
        )
    return code


def market_family_for_legacy_exchange(ex: str) -> MarketFamily:
    """Map an Indian or crypto legacy exchange string to a MarketFamily.

    US/EU exchanges are out of scope for the legacy path — raising
    ValueError there is intentional.
    """
    code = legacy_exchange_to_venue_code(ex)
    if code in _LEGACY_CRYPTO_EXCHANGES:
        return MarketFamily.CRYPTO
    return MarketFamily.IN_STOCK


def legacy_product_to_order_attrs(product: str) -> dict[str, Any]:
    """MIS / NRML / CNC → position-effect, TIF, session defaults.

    Keep this narrow: it returns only attributes that the NormalizedOrderRequest
    can consume directly. Settlement semantics live on the instrument/venue,
    not on the order. A brief note is returned for CNC for downstream loggers
    that care about delivery-vs-intraday distinctions.
    """
    if not isinstance(product, str):
        raise ValueError(f"legacy_product expects str, got {type(product).__name__}")
    key = product.strip().upper()
    if key not in _LEGACY_PRODUCTS:
        raise ValueError(
            f"Unknown legacy product {product!r}. Known: "
            f"{', '.join(sorted(_LEGACY_PRODUCTS))}"
        )

    if key == "MIS":
        return {
            "position_effect": PositionEffect.REDUCE_ONLY,
            "time_in_force": TimeInForce.DAY,
            "session": Session.REGULAR,
            "note": "intraday square-off",
        }
    if key == "NRML":
        return {
            "position_effect": PositionEffect.NONE,
            "time_in_force": TimeInForce.DAY,
            "session": Session.REGULAR,
            "note": "overnight carry (F&O)",
        }
    # CNC
    return {
        "position_effect": PositionEffect.NONE,
        "time_in_force": TimeInForce.DAY,
        "session": Session.REGULAR,
        "note": "cash-and-carry delivery",
    }


_PRICE_TYPE_MAP: dict[str, OrderType] = {
    "MARKET": OrderType.MARKET,
    "LIMIT": OrderType.LIMIT,
    "SL": OrderType.STOP_LIMIT,     # Indian SL is stop-loss LIMIT
    "SL-M": OrderType.STOP,         # Indian SL-M is stop-loss MARKET
}


def legacy_pricetype_to_order_type(pt: str) -> OrderType:
    """Indian price-type string → OrderType."""
    if not isinstance(pt, str):
        raise ValueError(f"legacy_pricetype expects str, got {type(pt).__name__}")
    key = pt.strip().upper()
    if key not in _PRICE_TYPE_MAP:
        raise ValueError(
            f"Unknown legacy price type {pt!r}. Known: "
            f"{', '.join(sorted(_LEGACY_PRICETYPES))}"
        )
    return _PRICE_TYPE_MAP[key]


def normalized_order_to_legacy_fields(order: Any) -> dict[str, Any]:
    """Project a NormalizedOrderRequest back into legacy Indian fields.

    Raises `UnsupportedCapability` for order shapes the legacy model
    cannot represent (MOO/MOC/LOO/LOC/TRAILING_STOP/PEGGED, non-DAY/
    non-IOC/non-FOK TIFs, non-REGULAR sessions, non-WHOLE/LOTS units).
    """
    # Imported here to keep translators module-loadable without orders
    from domain.enums import OrderType as OT
    from domain.enums import QuantityUnit as QU
    from domain.enums import Session as S
    from domain.enums import TimeInForce as TIF

    ot: OT = order.order_type
    tif: TIF = order.time_in_force
    sess: S = order.session
    qu: QU = order.quantity_unit

    # Map OrderType back to Indian price type
    if ot == OT.MARKET:
        pricetype = "MARKET"
    elif ot == OT.LIMIT:
        pricetype = "LIMIT"
    elif ot == OT.STOP_LIMIT:
        pricetype = "SL"
    elif ot == OT.STOP:
        pricetype = "SL-M"
    else:
        raise UnsupportedCapability(
            broker_code="legacy",
            capability_name=f"order_type={ot.value}",
            details="legacy Indian model supports MARKET, LIMIT, SL, SL-M only",
        )

    if tif not in {TIF.DAY, TIF.IOC, TIF.FOK}:
        raise UnsupportedCapability(
            broker_code="legacy",
            capability_name=f"time_in_force={tif.value}",
            details="legacy Indian model supports DAY/IOC/FOK only",
        )

    if sess != S.REGULAR:
        raise UnsupportedCapability(
            broker_code="legacy",
            capability_name=f"session={sess.value}",
            details="legacy Indian model has no extended-hours concept",
        )

    if qu not in {QU.WHOLE, QU.LOTS}:
        raise UnsupportedCapability(
            broker_code="legacy",
            capability_name=f"quantity_unit={qu.value}",
            details="legacy Indian model supports WHOLE and LOTS only",
        )

    # Position-effect → product mapping: REDUCE_ONLY → MIS; NONE → NRML
    # (futures/options) or CNC (equity). We cannot infer F&O-vs-equity
    # at this layer without an instrument. Default NONE → CNC; callers
    # that have F&O context override via `extra`.
    if order.position_effect == PositionEffect.REDUCE_ONLY:
        product = "MIS"
    else:
        product = str(order.extra.get("legacy_product_hint", "CNC"))

    return {
        "pricetype": pricetype,
        "product": product,
        "side": order.side.value,
    }


__all__ = [
    "legacy_exchange_to_venue_code",
    "legacy_pricetype_to_order_type",
    "legacy_product_to_order_attrs",
    "market_family_for_legacy_exchange",
    "normalized_order_to_legacy_fields",
]
