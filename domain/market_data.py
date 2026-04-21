"""Normalized market-data shapes.

All timestamps are tz-aware UTC. A `venue_timezone` field may be set
on bars when a renderer needs it, but canonical storage is UTC.
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from domain.currency import Currency
from domain.instrument_ref import InstrumentRef


def _require_utc(v: datetime) -> datetime:
    if v.tzinfo is None:
        raise ValueError("timestamp must be timezone-aware (UTC canonical)")
    # A tz-aware datetime whose utcoffset() is 0 we accept as UTC.
    # Other offsets pass through; callers can convert if they want.
    return v


class NormalizedQuote(BaseModel):
    """A point-in-time quote snapshot for a single instrument."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    instrument: InstrumentRef
    timestamp: datetime
    bid: Decimal | None = None
    ask: Decimal | None = None
    last: Decimal | None = None
    bid_size: Decimal | None = None
    ask_size: Decimal | None = None
    volume: Decimal | None = None
    currency: Currency | None = None

    @field_validator("timestamp")
    @classmethod
    def _tz_aware(cls, v: datetime) -> datetime:
        return _require_utc(v)


class NormalizedBar(BaseModel):
    """A single OHLCV bar."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    instrument: InstrumentRef
    period_start: datetime
    period_end: datetime
    interval: str  # "1m", "5m", "1h", "1d", etc. Free-form for now.
    open: Decimal
    high: Decimal
    low: Decimal
    close: Decimal
    volume: Decimal
    currency: Currency | None = None
    venue_timezone: str | None = None  # IANA hint; canonical storage is UTC

    @field_validator("period_start", "period_end")
    @classmethod
    def _tz_aware(cls, v: datetime) -> datetime:
        return _require_utc(v)


class NormalizedDepthLevel(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    price: Decimal
    size: Decimal


class NormalizedDepth(BaseModel):
    """Market depth (order book) snapshot."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    instrument: InstrumentRef
    timestamp: datetime
    bids: list[NormalizedDepthLevel] = Field(default_factory=list)
    asks: list[NormalizedDepthLevel] = Field(default_factory=list)
    currency: Currency | None = None

    @field_validator("timestamp")
    @classmethod
    def _tz_aware(cls, v: datetime) -> datetime:
        return _require_utc(v)


__all__ = [
    "NormalizedBar",
    "NormalizedDepth",
    "NormalizedDepthLevel",
    "NormalizedQuote",
]
