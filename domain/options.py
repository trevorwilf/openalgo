"""Phase 9 v4 (ADR 0027) — Options domain types.

Region-neutral types used by the OptionsProvider contract. India and
US providers parse / format / compute against these.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal
from enum import Enum
from typing import Any


class OptionRight(Enum):
    """The two option rights, region-neutral."""
    CALL = "CALL"
    PUT = "PUT"


@dataclass(frozen=True)
class OptionContract:
    """A single option contract.

    India: ``NIFTY28MAR2420800CE`` parses to:
        underlying="NIFTY", expiry=2024-03-28, right=CALL, strike=20800,
        lot_size=50 (NIFTY lot), multiplier=1, currency="INR",
        venue_code="NFO".

    US OCC OSI: ``AAPL  240419C00185000`` parses to:
        underlying="AAPL", expiry=2024-04-19, right=CALL, strike=185.0,
        lot_size=100, multiplier=100, currency="USD",
        venue_code="OPRA".
    """

    underlying: str
    expiry: date
    right: OptionRight
    strike: Decimal
    lot_size: int = 1
    multiplier: int = 1
    currency: str = "USD"
    venue_code: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class OptionChain:
    """A snapshot of all option contracts for one underlying + expiry."""

    underlying: str
    expiry: date
    calls: list[OptionContract] = field(default_factory=list)
    puts: list[OptionContract] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class Greeks:
    """Black-Scholes Greeks for one option contract."""

    delta: Decimal
    gamma: Decimal
    theta: Decimal
    vega: Decimal
    rho: Decimal | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class OIProfile:
    """Open-interest profile for one underlying + expiry.

    Maps strike → (call_oi, put_oi). Used by GEX / max-pain charts.
    """

    underlying: str
    expiry: date
    by_strike: dict[Decimal, tuple[Decimal, Decimal]]
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class MarketSnapshot:
    """Underlying + risk-free + dividend snapshot for option pricing."""

    underlying_price: Decimal
    risk_free_rate: Decimal = Decimal("0.05")
    dividend_yield: Decimal = Decimal("0")
    asof: date | None = None


__all__ = [
    "Greeks",
    "MarketSnapshot",
    "OIProfile",
    "OptionChain",
    "OptionContract",
    "OptionRight",
]
