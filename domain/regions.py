"""Market-region plugin model.

A market region is a lightweight, pluggable metadata bundle that gives
OpenAlgo a default regional context without hardcoding India/US/Europe
assumptions into the broker core. Regions are intentionally broader
than venues and narrower than brokers:

* venues = XNYS, XNAS, NSE, XLON
* regions = india, us, eu, uk
* brokers = zerodha, schwab, webull, ...

The current framework uses market-region plugins for:
* a default region setting in the Settings API,
* region-aware broker capability metadata (`supported_regions`), and
* future UI/runtime defaults such as timezone, currency, and default
  venue selection.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator

from domain.currency import Currency
from domain.enums import MarketFamily, Session


class MarketRegion(BaseModel):
    """Immutable metadata for a pluggable market region."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    region_code: str
    display_name: str
    description: str | None = None
    timezone_name: str
    market_families: list[MarketFamily]
    default_currency: Currency | None = None
    default_venue_codes: list[str] = Field(default_factory=list)
    default_sessions: list[Session] = Field(default_factory=list)
    country_codes: list[str] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)

    @field_validator("region_code", mode="before")
    @classmethod
    def _normalize_region_code(cls, value: Any) -> str:
        if not isinstance(value, str):
            raise ValueError("region_code must be a string")
        normalized = value.strip().lower().replace("-", "_").replace(" ", "_")
        if not normalized:
            raise ValueError("region_code cannot be empty")
        return normalized

    @field_validator("display_name")
    @classmethod
    def _display_name_not_blank(cls, value: str) -> str:
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("display_name cannot be empty")
        return cleaned


__all__ = ["MarketRegion"]
