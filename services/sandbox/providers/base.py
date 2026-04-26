"""Phase 8 v4 (ADR 0026) — SandboxProvider contract.

The Sandbox feature is provider-pluggable per ADR 0023 invariant 7.
Each region's sandbox semantics live in
``services/sandbox/providers/<region>/`` and implement the
:class:`SandboxProvider` Protocol below. The dispatcher in
:mod:`services.sandbox.dispatcher` selects the right provider for
the active broker's region.

Implementations:

* India provider — preserves the current
  T+1 settlement / MIS-CNC-NRML / ₹10,00,000 initial funds /
  15:15 IST square-off / no partial fills behavior bit-identically.
* US provider — mock data: T+2 equity / T+1 option settlement,
  USD $100k initial funds, basic partial-fill simulation, XNYS 16:00
  day-trade close.

New providers (EU, UK, future regions) follow the same Protocol.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal
from typing import TYPE_CHECKING, Any, Protocol, runtime_checkable

if TYPE_CHECKING:  # pragma: no cover
    from domain.orders import NormalizedOrderRequest


@dataclass(frozen=True)
class Fill:
    """One simulated fill for a sandbox order."""

    quantity: Decimal
    price: Decimal
    timestamp: datetime
    venue_code: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class MarketDataSnapshot:
    """Minimal market-data snapshot for fill simulation.

    The provider sees just what it needs: bid / ask / last / volume /
    timestamp. Sandbox does not need a full quote object.
    """

    bid: Decimal | None = None
    ask: Decimal | None = None
    last: Decimal | None = None
    volume: Decimal | None = None
    timestamp: datetime | None = None


@dataclass(frozen=True)
class ProviderRules:
    """Rules a provider exposes to the rest of the sandbox."""

    settlement_days_equity: int  # T+N (India: 1, US equity: 2)
    settlement_days_options: int  # T+N (India: 1, US option: 1)
    day_trade_close_required: bool  # India MIS, US DAY_TRADE
    overnight_allowed: bool  # India CNC/NRML, US OVERNIGHT/MARGIN
    partial_fills_supported: bool


@runtime_checkable
class SandboxProvider(Protocol):
    """Per-region sandbox semantics contract."""

    region_code: str

    def settlement_date_for_order(
        self, order: "NormalizedOrderRequest", trade_date: date,
    ) -> date:
        """Return the settlement date for an order placed on ``trade_date``.

        India: T+1 for equity, T+1 for options.
        US: T+2 for equity, T+1 for options.
        """

    def squareoff_time_for_product(
        self, product: str, venue_code: str, on_date: date,
    ) -> datetime | None:
        """Return the timezone-aware datetime by which a product must
        square off, or None when no auto-square-off applies (e.g.,
        India CNC/NRML, US OVERNIGHT)."""

    def simulate_fill(
        self,
        order: "NormalizedOrderRequest",
        market_data: MarketDataSnapshot,
    ) -> list[Fill]:
        """Simulate one or more fills for ``order`` against ``market_data``.

        India provider: single full fill at the market price.
        US provider: may return 2 partial fills for low-liquidity orders.
        """

    def supported_products(self) -> set[str]:
        """India: {"MIS", "CNC", "NRML"}; US: {"DAY_TRADE", "OVERNIGHT", "MARGIN"}."""

    def supported_order_types(self) -> set[str]:
        """The order types the sandbox can simulate."""

    def base_currency(self) -> str:
        """India: "INR"; US: "USD"."""

    def initial_funds(self) -> Decimal:
        """India: 1000000.00 (₹10L); US: 100000.00 ($100k)."""

    def partial_fills_supported(self) -> bool:
        ...

    def position_lifecycle_rules(self) -> ProviderRules:
        """Settlement / square-off / partial-fill rules in one struct."""


__all__ = [
    "Fill",
    "MarketDataSnapshot",
    "ProviderRules",
    "SandboxProvider",
]
