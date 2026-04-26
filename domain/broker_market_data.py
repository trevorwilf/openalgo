"""BrokerQuoteAdapter / BrokerBarAdapter — promoted-lane market-data
contracts.

Parallel to :mod:`domain.broker_translator`: per-broker adapters
provide quotes and bars without going through the legacy
``services.quotes_service`` / ``services.history_service`` entry
points. Registered into
:mod:`services.broker_market_data_registry` at startup and looked
up by the promoted dispatcher when
``API_V2_<BROKER_CODE_UPPER>`` is set.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from typing import TYPE_CHECKING, Any, Protocol, TypedDict, runtime_checkable

if TYPE_CHECKING:  # pragma: no cover
    from services.instrument_resolution import ResolvedInstrument


class AccountContext(TypedDict, total=False):
    broker_code: str
    auth_token: str
    base_currency: str


@dataclass(frozen=True)
class NormalizedQuote:
    """Broker-agnostic quote snapshot.

    Decimal fields are optional because not every broker populates
    every side of the book.
    """

    instrument_id: Any
    venue_code: str
    canonical_symbol: str
    bid: Decimal | None = None
    ask: Decimal | None = None
    last: Decimal | None = None
    bid_size: Decimal | None = None
    ask_size: Decimal | None = None
    timestamp: datetime | None = None
    currency: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class NormalizedBar:
    """One OHLCV bar in the broker's reported timezone.

    ``ts`` is the *open* time of the bar, timezone-aware.
    """

    ts: datetime
    open: Decimal
    high: Decimal
    low: Decimal
    close: Decimal
    volume: Decimal | None = None


@dataclass(frozen=True)
class NormalizedBarRequest:
    interval: str
    start: datetime
    end: datetime


@runtime_checkable
class BrokerQuoteAdapter(Protocol):
    """Per-broker quote-fetching contract for the promoted lane."""

    broker_code: str

    def get_quote(
        self,
        instrument: "ResolvedInstrument",
        account_ctx: AccountContext,
    ) -> NormalizedQuote:
        """Return a :class:`NormalizedQuote` for ``instrument``.

        Raises:
            domain.errors.UnsupportedCapability: the broker does not
                carry this instrument / venue.
        """


@runtime_checkable
class BrokerBarAdapter(Protocol):
    """Per-broker historical-bar contract for the promoted lane."""

    broker_code: str

    def get_bars(
        self,
        instrument: "ResolvedInstrument",
        request: NormalizedBarRequest,
        account_ctx: AccountContext,
    ) -> list[NormalizedBar]:
        """Return bars in chronological order (oldest first).

        Raises:
            domain.errors.UnsupportedCapability: the requested interval
                or range is unsupported.
        """


# Phase 5 v4 (ADR 0023, invariant 5) — promoted-lane account-state
# adapter Protocols. Mirror the BrokerQuoteAdapter / BrokerBarAdapter
# pattern. Mock plugins register stub implementations; real broker
# plugins replace them.

@dataclass(frozen=True)
class NormalizedPosition:
    """Broker-agnostic open position snapshot."""

    instrument_id: Any
    venue_code: str
    canonical_symbol: str
    quantity: Decimal
    average_price: Decimal | None = None
    market_value: Decimal | None = None
    realized_pnl: Decimal | None = None
    unrealized_pnl: Decimal | None = None
    currency: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class NormalizedBalance:
    """Broker-agnostic account balance snapshot."""

    cash: Decimal
    equity: Decimal | None = None
    buying_power: Decimal | None = None
    margin_used: Decimal | None = None
    currency: str = "USD"
    metadata: dict[str, Any] = field(default_factory=dict)


@runtime_checkable
class BrokerPositionAdapter(Protocol):
    """Per-broker open-positions contract for the promoted lane."""

    broker_code: str

    def get_positions(
        self,
        account_ctx: AccountContext,
    ) -> list[NormalizedPosition]:
        """Return all open positions for the account."""


@runtime_checkable
class BrokerBalanceAdapter(Protocol):
    """Per-broker account-balance contract for the promoted lane."""

    broker_code: str

    def get_balance(
        self,
        account_ctx: AccountContext,
    ) -> NormalizedBalance:
        """Return the account's balance snapshot."""


__all__ = [
    "AccountContext",
    "BrokerBalanceAdapter",
    "BrokerBarAdapter",
    "BrokerPositionAdapter",
    "BrokerQuoteAdapter",
    "NormalizedBalance",
    "NormalizedBar",
    "NormalizedBarRequest",
    "NormalizedPosition",
    "NormalizedQuote",
]
