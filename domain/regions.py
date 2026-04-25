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
* region-aware broker capability metadata (`supported_regions`),
* future UI/runtime defaults such as timezone, currency, and default
  venue selection, and
* (schema v2) authoritative venue catalog, session templates, calendar
  exceptions, symbol-display grammar, and per-region feature flags.

Schema v2 fields are all optional and default to empty so v1 plugins
continue to validate verbatim.
"""

from __future__ import annotations

from datetime import date, time
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from domain.currency import Currency
from domain.enums import MarketFamily, Session


# --- v2 sub-models -------------------------------------------------------


class VenueSeed(BaseModel):
    """Venue metadata declared by a region plugin.

    The region plugin is the source of truth for venue tz, currency,
    settlement template, and session model in the promoted lane.
    Phase 4 syncs these into the existing ``venues`` table via
    ``upgrade/seed_venue_schedule_defaults.py``; this model is the
    in-memory type the rest of the code consumes.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    venue_code: str
    display_name: str | None = None
    mic_code: str | None = None
    country_code: str | None = None
    timezone_name: str | None = None
    base_currency: str | None = None
    market_family: MarketFamily | None = None
    settlement_template: str | None = None
    session_model: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)

    @field_validator("venue_code")
    @classmethod
    def _venue_code_not_blank(cls, value: str) -> str:
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("venue_code cannot be empty")
        return cleaned


class SessionTemplateSeed(BaseModel):
    """A reusable session window in venue-local time.

    Either ``venue_code`` OR ``venue_codes`` may be present; the loader
    normalizes ``venue_code`` to a single-element ``venue_codes`` list
    so consumers always see ``venue_codes``.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    session_code: Session
    venue_codes: list[str] = Field(default_factory=list)
    local_start_time: time
    local_end_time: time
    days_of_week: list[int]
    effective_from: date | None = None
    effective_to: date | None = None
    label: str | None = None

    @field_validator("days_of_week")
    @classmethod
    def _validate_dow(cls, value: list[int]) -> list[int]:
        for d in value:
            if not 0 <= d <= 6:
                raise ValueError(f"days_of_week entry {d!r} out of range 0..6")
        return list(value)

    @model_validator(mode="before")
    @classmethod
    def _accept_single_venue_code(cls, data: Any) -> Any:
        if not isinstance(data, dict):
            return data
        if "venue_code" in data:
            single = data.pop("venue_code")
            existing = list(data.get("venue_codes") or [])
            if single and single not in existing:
                existing.insert(0, single)
            data["venue_codes"] = existing
        return data


class CalendarExceptionSeed(BaseModel):
    """One-off override for a venue's normal session window."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    date: date
    venue_code: str
    exception_type: str  # CLOSED | EARLY_CLOSE | LATE_OPEN | SPECIAL_SESSION
    local_start_time: time | None = None
    local_end_time: time | None = None
    reason: str | None = None
    source: str | None = None

    @field_validator("exception_type")
    @classmethod
    def _normalize_exception_type(cls, value: str) -> str:
        upper = value.strip().upper()
        if upper not in {"CLOSED", "EARLY_CLOSE", "LATE_OPEN", "SPECIAL_SESSION"}:
            raise ValueError(
                f"exception_type {value!r} must be one of CLOSED, "
                "EARLY_CLOSE, LATE_OPEN, SPECIAL_SESSION"
            )
        return upper


class SymbolDisplay(BaseModel):
    """Region-scoped symbol-grammar conventions used by display and parsing."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    date_format: str | None = None
    option_right_codes: list[str] = Field(default_factory=list)
    futures_grammar: str | None = None
    example_underlyings: list[str] = Field(default_factory=list)


class RegionFeatureFlags(BaseModel):
    """Per-region feature flags. Phase 6 reads these to gate option,
    flow, sandbox, and analyzer surfaces by active region."""

    model_config = ConfigDict(frozen=True, extra="allow")

    def is_enabled(self, name: str, default: bool = False) -> bool:
        value = getattr(self, name, None)
        if value is None and isinstance(self.__pydantic_extra__, dict):
            value = self.__pydantic_extra__.get(name)
        if value is None:
            return default
        return bool(value)


# --- top-level region model ---------------------------------------------


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

    # --- schema v2 (all optional, default empty) ---
    venues: list[VenueSeed] = Field(default_factory=list)
    session_templates: list[SessionTemplateSeed] = Field(default_factory=list)
    calendar_exceptions: list[CalendarExceptionSeed] = Field(default_factory=list)
    symbol_display: SymbolDisplay = Field(default_factory=SymbolDisplay)
    feature_flags: RegionFeatureFlags = Field(default_factory=RegionFeatureFlags)

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

    # --- v2 convenience accessors ---

    def get_venue(self, venue_code: str) -> VenueSeed | None:
        target = str(venue_code).strip()
        for venue in self.venues:
            if venue.venue_code == target:
                return venue
        return None

    def get_sessions_for(
        self, venue_code: str, *, on_date: date | None = None
    ) -> list[SessionTemplateSeed]:
        target = str(venue_code).strip()
        out: list[SessionTemplateSeed] = []
        for tpl in self.session_templates:
            if tpl.venue_codes and target not in tpl.venue_codes:
                continue
            if on_date is not None:
                if tpl.effective_from is not None and on_date < tpl.effective_from:
                    continue
                if tpl.effective_to is not None and on_date > tpl.effective_to:
                    continue
            out.append(tpl)
        return out

    def get_calendar_exceptions_for(
        self,
        venue_code: str,
        *,
        from_date: date | None = None,
        to_date: date | None = None,
    ) -> list[CalendarExceptionSeed]:
        target = str(venue_code).strip()
        out: list[CalendarExceptionSeed] = []
        for exc in self.calendar_exceptions:
            if exc.venue_code != target:
                continue
            if from_date is not None and exc.date < from_date:
                continue
            if to_date is not None and exc.date > to_date:
                continue
            out.append(exc)
        return out

    def is_feature_enabled(self, name: str, default: bool = False) -> bool:
        return self.feature_flags.is_enabled(name, default=default)


__all__ = [
    "CalendarExceptionSeed",
    "MarketRegion",
    "RegionFeatureFlags",
    "SessionTemplateSeed",
    "SymbolDisplay",
    "VenueSeed",
]
