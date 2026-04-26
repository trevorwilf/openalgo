"""Phase 9 v4 (ADR 0027) — OptionsProvider contract.

Per-region option semantics: symbol parsing / formatting, expiry
listing, chain retrieval, Greeks / IV / OI computation, supported
strategies.

India provider: DDMMMYY / CE-PE grammar.
US provider: OCC OSI 21-character format.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from typing import TYPE_CHECKING, Protocol, runtime_checkable

from domain.options import (
    Greeks,
    MarketSnapshot,
    OIProfile,
    OptionChain,
    OptionContract,
)

if TYPE_CHECKING:  # pragma: no cover
    from services.instrument_resolution import ResolvedInstrument


@runtime_checkable
class OptionsProvider(Protocol):
    """Per-region options semantics contract."""

    region_code: str

    def parse_option_symbol(self, symbol: str) -> OptionContract:
        """Parse a region-shaped option symbol into an OptionContract.

        Raises ``ValueError`` on grammar mismatch.
        """

    def format_option_symbol(self, contract: OptionContract) -> str:
        """Format an OptionContract back to the region's shape."""

    def list_expiries(self, underlying: str, asof: date) -> list[date]:
        """Return future expiry dates available for ``underlying``."""

    def get_chain(self, underlying: str, expiry: date) -> OptionChain:
        """Return the option chain for ``underlying`` at ``expiry``."""

    def compute_greeks(
        self, contract: OptionContract, market: MarketSnapshot, iv: Decimal,
    ) -> Greeks:
        """Compute Black-Scholes Greeks for ``contract`` at ``iv``."""

    def compute_iv(
        self, contract: OptionContract, premium: Decimal, market: MarketSnapshot,
    ) -> Decimal:
        """Solve for implied volatility from the observed ``premium``."""

    def compute_oi_profile(
        self, underlying: str, expiry: date,
    ) -> OIProfile:
        """Return the open-interest profile keyed by strike."""

    def supported_strategies(self) -> set[str]:
        """e.g., {"STRADDLE", "STRANGLE", "IRON_CONDOR"}."""

    def lot_size_for(self, contract: OptionContract) -> int:
        """Region-specific lot size resolution. India: per-underlying.
        US: 100 (standard equity options)."""


__all__ = ["OptionsProvider"]
