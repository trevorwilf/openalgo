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

from domain.enums import ComboType, OrderSide, OrderType, TimeInForce


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

# Order type: OpenAlgo OrderType ↔ Alpaca lowercase string. Branch I
# widened the supported set to include STOP / STOP_LIMIT /
# TRAILING_STOP; the translator now requires trigger_price for
# STOP / STOP_LIMIT and trailing_offset for TRAILING_STOP per the
# domain validator.
ORDER_TYPE_TO_ALPACA: dict[OrderType, str] = {
    OrderType.MARKET: "market",
    OrderType.LIMIT: "limit",
    OrderType.STOP: "stop",
    OrderType.STOP_LIMIT: "stop_limit",
    OrderType.TRAILING_STOP: "trailing_stop",
}
ALPACA_TO_ORDER_TYPE: dict[str, OrderType] = {
    "market": OrderType.MARKET,
    "limit": OrderType.LIMIT,
    "stop": OrderType.STOP,
    "stop_limit": OrderType.STOP_LIMIT,
    "trailing_stop": OrderType.TRAILING_STOP,
}
# SUPPORTED_ORDER_TYPES tracks the ROUND-TRIPPABLE types only. The
# auction order types (MARKET_ON_OPEN / LIMIT_ON_OPEN / *_ON_CLOSE)
# collapse to "market" / "limit" at the Alpaca side and the auction
# phase is carried by the TIF — that mapping is lossy on the
# reverse direction so the round-trip dictionaries above don't list
# them. The translator's _SUPPORTED_TYPES set in
# ``broker/alpaca/api/order_api.py`` is the union (5 simple + 4
# auction) and does the lossy translation inline.
SUPPORTED_ORDER_TYPES: frozenset[OrderType] = frozenset(
    {
        OrderType.MARKET,
        OrderType.LIMIT,
        OrderType.STOP,
        OrderType.STOP_LIMIT,
        OrderType.TRAILING_STOP,
    }
)

# Branch J — auction order types tracked separately. The translator
# treats these as legal inputs but their wire form is type=market /
# type=limit + the corresponding auction TIF (opg / cls).
AUCTION_ORDER_TYPES: frozenset[OrderType] = frozenset(
    {
        OrderType.MARKET_ON_OPEN,
        OrderType.LIMIT_ON_OPEN,
        OrderType.MARKET_ON_CLOSE,
        OrderType.LIMIT_ON_CLOSE,
    }
)

# Branch N — full ``OrderType → Alpaca wire string`` table including
# the auction collapse used by the translator's ``to_native``. This
# is the lossy-on-reverse map; ``ALPACA_TO_ORDER_TYPE`` above is the
# round-trippable subset.
ORDER_TYPE_NATIVE: dict[OrderType, str] = {
    OrderType.MARKET: "market",
    OrderType.LIMIT: "limit",
    OrderType.STOP: "stop",
    OrderType.STOP_LIMIT: "stop_limit",
    OrderType.TRAILING_STOP: "trailing_stop",
    # Auction variants collapse to plain market/limit at the wire
    # level — the auction phase is carried by the TIF (opg / cls).
    OrderType.MARKET_ON_OPEN: "market",
    OrderType.LIMIT_ON_OPEN: "limit",
    OrderType.MARKET_ON_CLOSE: "market",
    OrderType.LIMIT_ON_CLOSE: "limit",
}

# OrderTypes that carry a limit price on the wire (entry payload's
# ``limit_price`` field). Includes the auction LIMIT variants because
# they collapse to type=limit.
LIMIT_PRICED_ORDER_TYPES: frozenset[OrderType] = frozenset(
    {
        OrderType.LIMIT,
        OrderType.STOP_LIMIT,
        OrderType.LIMIT_ON_OPEN,
        OrderType.LIMIT_ON_CLOSE,
    }
)

# OrderTypes that carry a stop trigger on the wire (entry payload's
# ``stop_price`` field).
STOP_PRICED_ORDER_TYPES: frozenset[OrderType] = frozenset(
    {OrderType.STOP, OrderType.STOP_LIMIT}
)

# Time in force: OpenAlgo TimeInForce ↔ Alpaca lowercase string.
# Branch J — extended TIFs landed: IOC, FOK, OPG, ATC (Alpaca's
# wire form for ATC is the lowercase ``cls`` per the REST docs).
TIF_TO_ALPACA: dict[TimeInForce, str] = {
    TimeInForce.DAY: "day",
    TimeInForce.GTC: "gtc",
    TimeInForce.IOC: "ioc",
    TimeInForce.FOK: "fok",
    TimeInForce.OPG: "opg",
    TimeInForce.ATC: "cls",
}
ALPACA_TO_TIF: dict[str, TimeInForce] = {
    "day": TimeInForce.DAY,
    "gtc": TimeInForce.GTC,
    "ioc": TimeInForce.IOC,
    "fok": TimeInForce.FOK,
    "opg": TimeInForce.OPG,
    "cls": TimeInForce.ATC,
}
SUPPORTED_TIF: frozenset[TimeInForce] = frozenset(
    {
        TimeInForce.DAY,
        TimeInForce.GTC,
        TimeInForce.IOC,
        TimeInForce.FOK,
        TimeInForce.OPG,
        TimeInForce.ATC,
    }
)


def map_order_side(side: OrderSide) -> str:
    return SIDE_TO_ALPACA[side]


def map_order_type(order_type: OrderType) -> str:
    return ORDER_TYPE_TO_ALPACA[order_type]


def map_time_in_force(tif: TimeInForce) -> str:
    return TIF_TO_ALPACA[tif]


# ---------------------------------------------------------------------------
# Branch L — combo / bracket order class
# ---------------------------------------------------------------------------

# OpenAlgo ComboType → Alpaca REST ``order_class`` value. SINGLE
# omits the field entirely (Alpaca defaults to ``simple``).
#
# ``BRACKET`` (the canonical "parent + take-profit + stop-loss"
# pattern) is functionally identical to Alpaca's ``bracket``
# order_class, which OpenAlgo also exposes as ``OTOCO``. The
# translator accepts both — operators picking the more obviously-
# named ``BRACKET`` get the same Alpaca payload.
COMBO_TYPE_TO_ALPACA: dict[ComboType, str] = {
    ComboType.OTO: "oto",
    ComboType.OCO: "oco",
    ComboType.OTOCO: "bracket",
    ComboType.BRACKET: "bracket",
}
SUPPORTED_COMBO_TYPES: frozenset[ComboType] = frozenset(
    {
        ComboType.SINGLE,
        ComboType.OTO,
        ComboType.OCO,
        ComboType.OTOCO,
        ComboType.BRACKET,
    }
)


# ---------------------------------------------------------------------------
# Branch M — crypto venue + Branch K extended-hours session set
# ---------------------------------------------------------------------------

CRYPTO_VENUES: frozenset[str] = frozenset({"CRYPTO"})

# Sessions that route to Alpaca's ``extended_hours=true`` flag.
# Imported from domain.enums lazily to avoid the circular when
# Session is imported into this module.
from domain.enums import Session  # noqa: E402

EXTENDED_HOURS_SESSIONS: frozenset[Session] = frozenset(
    {Session.PRE_MARKET, Session.POST_MARKET, Session.EXTENDED}
)
SUPPORTED_SESSIONS: frozenset[Session] = frozenset(
    {Session.REGULAR, Session.PRE_MARKET, Session.POST_MARKET, Session.EXTENDED}
)


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
    "AUCTION_ORDER_TYPES",
    "COMBO_TYPE_TO_ALPACA",
    "CRYPTO_VENUES",
    "EXTENDED_HOURS_SESSIONS",
    "LIMIT_PRICED_ORDER_TYPES",
    "ORDER_TYPE_NATIVE",
    "ORDER_TYPE_TO_ALPACA",
    "SIDE_TO_ALPACA",
    "STOP_PRICED_ORDER_TYPES",
    "SUPPORTED_COMBO_TYPES",
    "SUPPORTED_ORDER_TYPES",
    "SUPPORTED_SESSIONS",
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
