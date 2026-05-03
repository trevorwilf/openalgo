"""Enum vocabulary for market-agnostic domain types.

All enums are `StrEnum` so serialized values are human-readable and
JSON-friendly. Enum *values* are the wire/storage representation;
enum *names* are for Python code. Keep the values stable — renaming a
value is a breaking change.

Design targets are Indian, US, European equities, and crypto. Specific
broker SDKs are out of scope (ADR 0002).
"""

from __future__ import annotations

from enum import StrEnum


class MarketFamily(StrEnum):
    """A coarse grouping of venues. Specific exchanges are Venues, not families."""

    IN_STOCK = "IN_STOCK"
    US_STOCK = "US_STOCK"
    EU_STOCK = "EU_STOCK"
    UK_STOCK = "UK_STOCK"
    CRYPTO = "CRYPTO"
    FUTURES = "FUTURES"
    FX = "FX"
    COMMODITY = "COMMODITY"
    OTHER = "OTHER"


class AssetClass(StrEnum):
    """What kind of instrument this is, independently of the venue."""

    EQUITY = "EQUITY"
    ETF = "ETF"
    FUTURE = "FUTURE"
    OPTION = "OPTION"
    PERPETUAL = "PERPETUAL"
    SPOT = "SPOT"
    INDEX = "INDEX"
    BOND = "BOND"
    WARRANT = "WARRANT"
    STRUCTURED = "STRUCTURED"
    OTHER = "OTHER"


class InstrumentKind(StrEnum):
    """Coarse derivative/cash taxonomy used for margin and settlement logic."""

    CASH = "CASH"
    DERIVATIVE = "DERIVATIVE"
    SYNTHETIC = "SYNTHETIC"
    NOTIONAL = "NOTIONAL"


class OrderSide(StrEnum):
    BUY = "BUY"
    SELL = "SELL"


class OrderType(StrEnum):
    """Covers Indian, US, and European execution types.

    MOO/MOC/LOO/LOC cover US open/close and European auctions.
    TRAILING_STOP is widely used in US retail.
    """

    MARKET = "MARKET"
    LIMIT = "LIMIT"
    STOP = "STOP"
    STOP_LIMIT = "STOP_LIMIT"
    TRAILING_STOP = "TRAILING_STOP"
    MARKET_ON_OPEN = "MARKET_ON_OPEN"
    MARKET_ON_CLOSE = "MARKET_ON_CLOSE"
    LIMIT_ON_OPEN = "LIMIT_ON_OPEN"
    LIMIT_ON_CLOSE = "LIMIT_ON_CLOSE"
    PEGGED = "PEGGED"


class TimeInForce(StrEnum):
    """Time-in-force semantics.

    GTD requires an accompanying `good_till` datetime on the order.
    OPG is at-the-opening (auction only). ATC is at-the-close.
    """

    DAY = "DAY"
    GTC = "GTC"
    GTD = "GTD"
    IOC = "IOC"
    FOK = "FOK"
    OPG = "OPG"
    ATC = "ATC"


class Session(StrEnum):
    """Which session window an order targets.

    ALL_DAY covers 24/7 crypto. European cash markets use opening and
    closing auctions. US has pre and post market windows.
    """

    PRE_MARKET = "PRE_MARKET"
    OPENING_AUCTION = "OPENING_AUCTION"
    REGULAR = "REGULAR"
    INTRADAY_AUCTION = "INTRADAY_AUCTION"
    CLOSING_AUCTION = "CLOSING_AUCTION"
    POST_MARKET = "POST_MARKET"
    EXTENDED = "EXTENDED"
    ALL_DAY = "ALL_DAY"


class QuantityUnit(StrEnum):
    """How `quantity` on an order is interpreted."""

    WHOLE = "WHOLE"               # integer shares / equity unit
    FRACTIONAL = "FRACTIONAL"     # decimal shares (US retail fractional)
    NOTIONAL = "NOTIONAL"         # currency amount (buy $100 of X)
    CONTRACTS = "CONTRACTS"       # futures/options contracts
    LOTS = "LOTS"                 # Indian-style lot-sized trading


class SettlementType(StrEnum):
    T0 = "T0"
    T1 = "T1"
    T2 = "T2"
    T_PLUS_N = "T_PLUS_N"
    IMMEDIATE = "IMMEDIATE"
    ROLLING = "ROLLING"


class PositionEffect(StrEnum):
    """Directive for what a trade does to an existing position.

    NONE is the default for markets that do not carry this concept.
    REDUCE_ONLY maps from Indian-style MIS behavior at the translator.
    """

    OPEN = "OPEN"
    CLOSE = "CLOSE"
    REDUCE_ONLY = "REDUCE_ONLY"
    NONE = "NONE"


class OptionRight(StrEnum):
    CALL = "CALL"
    PUT = "PUT"


class ComboType(StrEnum):
    """Multi-leg / linked-order families.

    Phase 8 — added to support Schwab OrderStrategyType, Webull combo
    orders, and bracket / OTO / OCO strategies that single-leg
    NormalizedOrderRequest cannot express.

    SINGLE   - one leg, identical semantics to NormalizedOrderRequest.
    OTO      - One Triggers Other (parent fills → trigger child).
    OCO      - One Cancels Other (siblings; whichever fills cancels the
               others).
    OTOCO    - One Triggers OCO (parent fills → activate an OCO group).
    COMBO    - Spread / strategy combo treated as a single execution
               unit (Schwab's COMBO).
    MULTILEG_OPTIONS - explicit multi-leg options spread/butterfly/
               iron condor.
    ICEBERG  - Iceberg (display only a slice).
    BRACKET  - parent + take-profit + stop-loss (US retail style).
    """

    SINGLE = "SINGLE"
    OTO = "OTO"
    OCO = "OCO"
    OTOCO = "OTOCO"
    COMBO = "COMBO"
    MULTILEG_OPTIONS = "MULTILEG_OPTIONS"
    ICEBERG = "ICEBERG"
    BRACKET = "BRACKET"


class StreamTransport(StrEnum):
    """Transport flavor a broker streaming adapter uses."""

    WEBSOCKET = "WEBSOCKET"
    MQTT = "MQTT"
    GRPC = "GRPC"
    SSE = "SSE"
    POLL = "POLL"


class AuthMode(StrEnum):
    """Authentication style declared by a broker plugin.

    SIGNATURE — broker requires per-request HMAC signature
        (Webull-direct OpenAPI, Binance, etc.).
    OAUTH    — three-legged OAuth flow (Schwab, Webull Connect, Alpaca
        OAuth-paper).
    API_KEY  — static key + secret pair (most legacy India brokers).
    SESSION_TOKEN — interactive login → session token (legacy India
        brokers that mint a daily token).
    """

    SIGNATURE = "SIGNATURE"
    OAUTH = "OAUTH"
    API_KEY = "API_KEY"
    SESSION_TOKEN = "SESSION_TOKEN"


class OrderStatus(StrEnum):
    """Canonical, broker-agnostic order lifecycle states.

    Vocabulary intentionally mirrors FIX 4.4 OrdStatus (tag 39) so the
    promoted lane stays interoperable with the international standard
    most institutional brokers (US, EU, APAC) speak fluently. The
    sequence is:

        PENDING_NEW   → broker has received the order, not yet acked
        NEW           → acked by exchange, sitting in the book unfilled
        WORKING       → live and actively being executed (US / Schwab term)
        PARTIALLY_FILLED → some quantity filled, more remaining
        FILLED        → complete fill — terminal success
        DONE_FOR_DAY  → day order ran out of session without filling
        CANCELED      → operator-canceled (terminal)
        EXPIRED       → time-in-force expired (terminal)
        REJECTED      → broker rejected the order outright (terminal)
        SUSPENDED     → held by the broker (compliance / margin / etc.)
        TRIGGER_PENDING → stop / SL trigger condition not yet met
                           (legacy Indian behavior)
        PENDING_CANCEL → cancel requested, not yet effective
        PENDING_REPLACE → modify requested, not yet effective
        REPLACED      → modified — original superseded by a new id
        ACCEPTED_FOR_BIDDING → OTC-style auction acceptance
        CALCULATED    → broker calculated execution but not yet routed
        UNKNOWN       → broker reported a state we don't recognize

    Per-broker translators map their native vocabulary to these values
    via :meth:`BrokerOrderTranslator.normalize_order_status`.
    Display layers (legacy India UI, modern v2 UI, telegram bot, etc.)
    consume the canonical enum and render whatever language the
    surface needs (``services.order_status_display``).
    """

    PENDING_NEW = "PENDING_NEW"
    NEW = "NEW"
    WORKING = "WORKING"
    PARTIALLY_FILLED = "PARTIALLY_FILLED"
    FILLED = "FILLED"
    DONE_FOR_DAY = "DONE_FOR_DAY"
    CANCELED = "CANCELED"
    EXPIRED = "EXPIRED"
    REJECTED = "REJECTED"
    SUSPENDED = "SUSPENDED"
    TRIGGER_PENDING = "TRIGGER_PENDING"
    PENDING_CANCEL = "PENDING_CANCEL"
    PENDING_REPLACE = "PENDING_REPLACE"
    REPLACED = "REPLACED"
    ACCEPTED_FOR_BIDDING = "ACCEPTED_FOR_BIDDING"
    CALCULATED = "CALCULATED"
    UNKNOWN = "UNKNOWN"

    @property
    def is_terminal(self) -> bool:
        """True when no further state transitions are expected."""
        return self in {
            OrderStatus.FILLED,
            OrderStatus.CANCELED,
            OrderStatus.EXPIRED,
            OrderStatus.REJECTED,
            OrderStatus.DONE_FOR_DAY,
            OrderStatus.REPLACED,
        }

    @property
    def is_open(self) -> bool:
        """True while the order can still take or place fills."""
        return self in {
            OrderStatus.PENDING_NEW,
            OrderStatus.NEW,
            OrderStatus.WORKING,
            OrderStatus.PARTIALLY_FILLED,
            OrderStatus.SUSPENDED,
            OrderStatus.TRIGGER_PENDING,
            OrderStatus.PENDING_CANCEL,
            OrderStatus.PENDING_REPLACE,
            OrderStatus.ACCEPTED_FOR_BIDDING,
            OrderStatus.CALCULATED,
        }


class IdentifierType(StrEnum):
    """Categories of alternative identifier that can resolve an instrument."""

    ISIN = "ISIN"
    CUSIP = "CUSIP"
    SEDOL = "SEDOL"
    FIGI = "FIGI"
    RIC = "RIC"
    VENUE_SYMBOL = "VENUE_SYMBOL"
    BROKER_TOKEN = "BROKER_TOKEN"
    BROKER_SYMBOL = "BROKER_SYMBOL"
    CANONICAL_SYMBOL = "CANONICAL_SYMBOL"
    INTERNAL_ID = "INTERNAL_ID"


__all__ = [
    "AssetClass",
    "AuthMode",
    "ComboType",
    "IdentifierType",
    "InstrumentKind",
    "MarketFamily",
    "OptionRight",
    "OrderSide",
    "OrderStatus",
    "OrderType",
    "PositionEffect",
    "QuantityUnit",
    "Session",
    "SettlementType",
    "StreamTransport",
    "TimeInForce",
]
