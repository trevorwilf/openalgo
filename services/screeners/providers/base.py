"""Phase 10 v4 (ADR 0028) — ScreenerProvider contract.

A screener provider parses webhook payloads from a third-party
screener (Chartink, future TradingView screeners, etc.) and maps the
signal into one or more :class:`NormalizedOrderRequest` objects.

Multiple screener providers can be registered; each is keyed by
``provider_code`` (e.g., "chartink"). The active broker's
capability metadata (``BrokerCapabilities.supports_screener_providers``)
determines which providers the broker can route signals through.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from typing import TYPE_CHECKING, Any, Protocol, runtime_checkable

if TYPE_CHECKING:  # pragma: no cover
    from domain.orders import NormalizedOrderRequest


@dataclass(frozen=True)
class ScreenerSignal:
    """A normalized screener signal — what the provider produces from
    a webhook payload."""

    signal_type: str  # "buy" | "sell" | "exit"
    symbols: list[str] = field(default_factory=list)
    price: Decimal | None = None
    timestamp: datetime | None = None
    raw_payload: dict[str, Any] = field(default_factory=dict)
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class ScreenerConfig:
    """Per-strategy configuration the user supplies (quantity, product,
    venue, etc.) — applied uniformly to every order produced by
    ``map_signal_to_orders``."""

    quantity: Decimal
    product: str
    venue_code: str | None = None
    order_type: str = "MARKET"
    metadata: dict[str, Any] = field(default_factory=dict)


@runtime_checkable
class ScreenerProvider(Protocol):
    """Per-screener-provider contract."""

    provider_code: str  # e.g., "chartink"
    region_code: str  # e.g., "india"
    supported_venues: list[str]

    def validate_webhook_payload(self, payload: dict) -> ScreenerSignal:
        """Parse + validate the provider's webhook payload.

        Raises ``ValueError`` on payload-shape mismatch.
        """

    def supported_signal_types(self) -> set[str]:
        """e.g., {"buy", "sell", "exit"}."""

    def map_signal_to_orders(
        self, signal: ScreenerSignal, config: ScreenerConfig,
    ) -> list["NormalizedOrderRequest"]:
        """Map the parsed signal into one or more
        :class:`NormalizedOrderRequest` objects (one per symbol)."""


__all__ = ["ScreenerConfig", "ScreenerProvider", "ScreenerSignal"]
