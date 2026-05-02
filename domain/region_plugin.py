"""Phase 7 — RegionPlugin Protocol.

The runtime contract every market-region package satisfies. Region
data lives at ``market_regions/<code>/``; the package's ``plugin.py``
exposes a ``RegionPlugin``-implementing class that ``utils.region_loader``
instantiates and caches once per loaded region.

The Protocol is the framework's stable surface for region-aware
behavior:

* ``manifest()`` — the JSON-loaded :class:`MarketRegion` (already the
  v2 / v3 schema).
* ``timezone_object()`` — a ``pytz``- or ``zoneinfo``-flavored tz
  object the rest of the codebase imports as the region's IST / EST /
  CET / GMT.
* ``holiday_calendar(year)`` — calendar-exception entries (closed days
  + special sessions) for a given year.
* ``session_templates()``, ``squareoff_rules()``, ``qty_freeze_rules()``,
  ``options_grammar()``, ``index_classification()``, ``locale()``,
  ``settlement_template(venue)`` — the data tables relocated in
  Phase 2.
* ``sandbox_provider()``, ``options_provider()``, ``screener_providers()``
  — handles to the registered providers for this region.

Implementations live under ``market_regions/<code>/plugin.py`` and
should compose, not duplicate, the region's data modules
(``holidays.py``, ``sessions.py``, etc.). See
:class:`market_regions.india.plugin.IndiaRegionPlugin` and
:class:`market_regions.us.plugin.USRegionPlugin` for the canonical
implementations.

This module is PROMOTED_CORE per
``scripts/audit/classification_rules.yaml`` — the contract is region-
neutral.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Protocol, runtime_checkable

if TYPE_CHECKING:  # pragma: no cover
    from datetime import tzinfo

    from domain.regions import (
        CalendarExceptionSeed,
        MarketRegion,
        SessionTemplateSeed,
    )


@runtime_checkable
class RegionPlugin(Protocol):
    """Runtime contract for a region-plugin Python package.

    Implementations are registered through
    :mod:`utils.region_loader` and resolved via
    :func:`utils.region_loader.get_region_plugin`.
    """

    region_code: str

    def manifest(self) -> "MarketRegion":
        """The parsed ``plugin.json`` :class:`MarketRegion` instance.

        Implementations typically return a cached single instance —
        the manifest is small and immutable per app boot.
        """
        ...

    def timezone_object(self) -> "tzinfo":
        """Single source of truth for the region's IANA timezone.

        Implementations should return the same object identity on
        repeated calls so callers can compare with ``is`` (the
        :class:`market_regions.india.sessions.IST` re-export pattern).
        """
        ...

    def holiday_calendar(self, year: int) -> list["CalendarExceptionSeed"]:
        """Calendar exceptions (CLOSED / SPECIAL_SESSION / EARLY_CLOSE)
        for ``year``. Returns an empty list when no entries exist.
        Callers stitch this into ``database.market_calendar_db`` /
        ``database.venue_schedule_repo`` per their own caching rules.
        """
        ...

    def session_templates(self) -> list["SessionTemplateSeed"]:
        """Per-venue session windows in venue-local time."""
        ...

    def squareoff_rules(self) -> list[dict[str, Any]]:
        """``MarketRegion.mandatory_close_rules``-shaped list of
        per-venue auto-close rules. India: MIS 15:15 / 16:45 / 23:30
        / 17:00 by venue. US: DAY_TRADE 16:00 ET on equity venues."""
        ...

    def qty_freeze_rules(self) -> list[dict[str, Any]]:
        """``MarketRegion.quantity_freeze_rules``-shaped list. India:
        single NFO row pointing at ``data/qtyfreeze.csv``. US: empty
        — no equivalent regulatory freeze concept."""
        ...

    def options_grammar(self) -> dict[str, Any]:
        """Aggregate dict of the region's option-symbol grammar
        (date format, right codes, regex pattern, lot-size table,
        index classification, equity-index expiry cutoff).
        India: DDMMMYY + CE/PE. US: OCC OSI 21-character format."""
        ...

    def index_classification(self) -> dict[str, list[str]]:
        """Venue → list of corresponding index venue codes. India:
        ``{NSE: [NSE_INDEX], BSE: [BSE_INDEX]}``. US: empty (US index
        symbols share the equity venue codes)."""
        ...

    def locale(self) -> dict[str, Any]:
        """Region's currency / number-formatting metadata.
        Includes the BCP-47 locale tag, currency code, currency
        symbol, and any region-specific suffix thresholds (India's
        Cr / L)."""
        ...

    def settlement_template(self, venue: str) -> str:
        """Equity-cash settlement convention for ``venue``. T+1 / T+0
        / T+2 are the canonical strings."""
        ...

    def sandbox_provider(self) -> Any:
        """Handle to the region's :class:`SandboxProvider` (per
        ADR 0026). May raise if not registered for this region."""
        ...

    def options_provider(self) -> Any:
        """Handle to the region's :class:`OptionsProvider` (per
        ADR 0027). May raise if not registered for this region."""
        ...

    def screener_providers(self) -> list[str]:
        """Provider codes registered for this region (per ADR 0028).
        India: ``["chartink"]``. US: empty — provider-driven."""
        ...


__all__ = ["RegionPlugin"]
