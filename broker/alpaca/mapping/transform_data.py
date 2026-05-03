"""Alpaca ↔ OpenAlgo vocabulary round-trip.

Single source of truth for mapping OpenAlgo's normalized order /
venue / symbol fields to Alpaca's REST API string vocabulary.

The order translator (``broker/alpaca/api/order_api.py``) currently
inlines several of these maps; the streaming adapter
(``broker/alpaca/streaming/alpaca_adapter.py``) inlines a tape →
venue map; the instrument-sync adapters
(``broker/alpaca/sync/instrument_sync.py``,
``services/instrument_sync_adapters/alpaca_adapter.py``) inline an
exchange → venue map. Branch G publishes this module as the
canonical home; the inline copies remain intentionally consistent
with these tables and a future cleanup can migrate them to import
from here.

Conventions:
  * ``XNAS / XNYS / ARCX / BATS / IEXG`` are OpenAlgo's MIC-style
    canonical venue codes for the venues Alpaca trades against.
  * Alpaca's REST API uses verbose strings (``NASDAQ``, ``NYSE``,
    ``ARCA``, ``BATS``) for asset listings and tape letters
    (``Q``, ``N``, ``P``, ``Z``, ``V``) for trade / quote frames.
"""

from __future__ import annotations

from domain.enums import OrderSide, OrderType, TimeInForce


# ---------------------------------------------------------------------------
# Venue mapping
# ---------------------------------------------------------------------------

# Alpaca's verbose exchange string (returned by /v2/assets) → canonical
# OpenAlgo venue_code. AMEX folds to XNYS (NYSE subsidiary); OTC folds
# to XNAS (best-effort routing for unlisted issues).
ALPACA_EXCHANGE_TO_VENUE: dict[str, str] = {
    "NASDAQ": "XNAS",
    "NYSE": "XNYS",
    "ARCA": "ARCX",
    "BATS": "BATS",
    "AMEX": "XNYS",
    "OTC": "XNAS",
    "IEX": "IEXG",
}

# Reverse — OpenAlgo venue → Alpaca exchange string. Used for any
# call that needs to feed Alpaca a venue filter (eg. quote routing).
VENUE_TO_ALPACA_EXCHANGE: dict[str, str] = {
    "XNAS": "NASDAQ",
    "XNYS": "NYSE",
    "ARCX": "ARCA",
    "BATS": "BATS",
    "IEXG": "IEX",
}

# Tape letter (in trade / quote WS frames) → canonical OpenAlgo venue.
ALPACA_TAPE_TO_VENUE: dict[str, str] = {
    "V": "IEXG",
    "Q": "XNAS",
    "N": "XNYS",
    "P": "ARCX",
    "Z": "BATS",
}

# Set of venues the order-routing translator currently accepts.
SUPPORTED_VENUES: frozenset[str] = frozenset(
    {"XNAS", "XNYS", "ARCX", "BATS"}
)


def venue_from_alpaca_exchange(exchange: str | None) -> str | None:
    """Map an Alpaca exchange string to canonical venue, or None
    when the mapping is unknown.
    """
    if not exchange:
        return None
    return ALPACA_EXCHANGE_TO_VENUE.get(exchange.strip().upper())


def venue_from_alpaca_tape(tape: str | None) -> str:
    """Map an Alpaca tape letter (from a trade / quote frame) to
    canonical venue. Falls back to XNAS when the tape is unknown
    or absent — the framework never fail-opens a tick for missing
    tape data; the caller can override this with capability lookups.
    """
    if tape and tape in ALPACA_TAPE_TO_VENUE:
        return ALPACA_TAPE_TO_VENUE[tape]
    return "XNAS"


# ---------------------------------------------------------------------------
# Order vocabulary
# ---------------------------------------------------------------------------

# Side: OpenAlgo OrderSide ↔ Alpaca lowercase string.
SIDE_TO_ALPACA: dict[OrderSide, str] = {
    OrderSide.BUY: "buy",
    OrderSide.SELL: "sell",
}
ALPACA_TO_SIDE: dict[str, OrderSide] = {
    "buy": OrderSide.BUY,
    "sell": OrderSide.SELL,
}

# Order type: OpenAlgo OrderType ↔ Alpaca lowercase string. The order
# translator currently supports MARKET + LIMIT; STOP / STOP_LIMIT /
# TRAILING_STOP are listed here for forward compatibility — adding a
# new supported type means widening the SUPPORTED_ORDER_TYPES set
# below AND the validate() check in order_api.py.
ORDER_TYPE_TO_ALPACA: dict[OrderType, str] = {
    OrderType.MARKET: "market",
    OrderType.LIMIT: "limit",
    # Forward-compat (not in SUPPORTED_ORDER_TYPES yet):
    # OrderType.STOP_MARKET: "stop",
    # OrderType.STOP_LIMIT: "stop_limit",
    # OrderType.TRAILING_STOP: "trailing_stop",
}
ALPACA_TO_ORDER_TYPE: dict[str, OrderType] = {
    "market": OrderType.MARKET,
    "limit": OrderType.LIMIT,
}
SUPPORTED_ORDER_TYPES: frozenset[OrderType] = frozenset(
    {OrderType.MARKET, OrderType.LIMIT}
)

# Time in force: OpenAlgo TimeInForce ↔ Alpaca lowercase string.
TIF_TO_ALPACA: dict[TimeInForce, str] = {
    TimeInForce.DAY: "day",
    TimeInForce.GTC: "gtc",
    # Forward-compat (Alpaca supports these but the translator
    # currently rejects anything outside DAY/GTC):
    # TimeInForce.IOC: "ioc",
    # TimeInForce.FOK: "fok",
    # TimeInForce.OPG: "opg",
    # TimeInForce.ATC: "cls",   # Alpaca: at-close → "cls"
}
ALPACA_TO_TIF: dict[str, TimeInForce] = {
    "day": TimeInForce.DAY,
    "gtc": TimeInForce.GTC,
}
SUPPORTED_TIF: frozenset[TimeInForce] = frozenset(
    {TimeInForce.DAY, TimeInForce.GTC}
)


def map_order_side(side: OrderSide) -> str:
    return SIDE_TO_ALPACA[side]


def map_order_type(order_type: OrderType) -> str:
    return ORDER_TYPE_TO_ALPACA[order_type]


def map_time_in_force(tif: TimeInForce) -> str:
    return TIF_TO_ALPACA[tif]


# ---------------------------------------------------------------------------
# Symbol round-trip
# ---------------------------------------------------------------------------

# US equities: OpenAlgo's canonical_symbol IS Alpaca's symbol — both use
# the bare ticker (``AAPL``, ``TSLA``). The helpers exist for symmetry
# with other broker plugins where the round-trip is non-trivial; they
# also future-proof the crypto path where Alpaca uses ``BTC/USD`` and
# OpenAlgo's normalized form is typically ``BTC-USD``.

def to_alpaca_symbol(canonical_symbol: str, asset_class: str = "EQUITY") -> str:
    """OpenAlgo canonical → Alpaca-API symbol.

    For US equities the round-trip is identity. For crypto it
    converts the OpenAlgo dash separator to Alpaca's slash form.
    """
    if asset_class == "SPOT" and "-" in canonical_symbol:
        return canonical_symbol.replace("-", "/")
    return canonical_symbol


def from_alpaca_symbol(alpaca_symbol: str, asset_class: str = "EQUITY") -> str:
    """Alpaca-API symbol → OpenAlgo canonical."""
    if asset_class == "SPOT" and "/" in alpaca_symbol:
        return alpaca_symbol.replace("/", "-")
    return alpaca_symbol


__all__ = [
    "ALPACA_EXCHANGE_TO_VENUE",
    "ALPACA_TAPE_TO_VENUE",
    "ALPACA_TO_ORDER_TYPE",
    "ALPACA_TO_SIDE",
    "ALPACA_TO_TIF",
    "ORDER_TYPE_TO_ALPACA",
    "SIDE_TO_ALPACA",
    "SUPPORTED_ORDER_TYPES",
    "SUPPORTED_TIF",
    "SUPPORTED_VENUES",
    "TIF_TO_ALPACA",
    "VENUE_TO_ALPACA_EXCHANGE",
    "from_alpaca_symbol",
    "map_order_side",
    "map_order_type",
    "map_time_in_force",
    "to_alpaca_symbol",
    "venue_from_alpaca_exchange",
    "venue_from_alpaca_tape",
]
