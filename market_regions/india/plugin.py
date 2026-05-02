"""IndiaRegionPlugin — composes the Phase 2 data modules into a
:class:`domain.region_plugin.RegionPlugin` instance.

Phase 7a wires the relocated India data (holidays, IST tz, MIS
squareoff rules, qty-freeze, options grammar, locale) into a single
runtime-contract object that ``utils.region_loader`` instantiates
once per process. The class delegates every method to the existing
relocated modules — Phase 7 ships **no behavior change** for India.

This file is REGION_PLUGIN-classified. See ADR 0006 for the literal-
scanner exemption.
"""

from __future__ import annotations

from datetime import date
from typing import TYPE_CHECKING, Any

from market_regions.india.holidays import HOLIDAYS_2026
from market_regions.india.locale import INDIAN_CURRENCY_LOCALE
from market_regions.india.options_grammar import (
    INDEX_CLASSIFICATION as _INDIA_INDEX_CLASSIFICATION,
)
from market_regions.india.options_grammar import OPTION_GRAMMAR as _INDIA_OPTION_GRAMMAR
from market_regions.india.qty_freeze import QUANTITY_FREEZE_RULES
from market_regions.india.sessions import IST
from market_regions.india.squareoff import MANDATORY_CLOSE_RULES

if TYPE_CHECKING:  # pragma: no cover
    from datetime import tzinfo

    from domain.regions import (
        CalendarExceptionSeed,
        MarketRegion,
        SessionTemplateSeed,
    )


REGION_CODE: str = "india"


def _coerce_holiday_to_seed(entry: dict[str, Any], year: int) -> dict[str, Any]:
    """Project a HOLIDAYS_2026-shaped dict into the
    ``CalendarExceptionSeed``-compatible shape consumers expect.

    The HOLIDAYS_2026 list carries the v6 calendar shape (date,
    description, holiday_type, closed[], open[]); the v2 region-plugin
    schema's ``calendar_exceptions`` uses (date, venue_code,
    exception_type, ...). The bridging happens here so the seeder in
    ``database.market_calendar_db`` can keep its existing format and
    new consumers see the canonical shape.
    """
    return dict(entry)  # pass-through for now; Phase 7 keeps the shape


class IndiaRegionPlugin:
    """:class:`RegionPlugin` implementation for India.

    Stateless aside from the manifest cache, which is populated lazily
    on first ``manifest()`` call. Every method delegates to the
    relocated data modules — adding a new India holiday is a single
    edit to ``market_regions/india/holidays.py``; adding a new venue
    is a single edit to ``market_regions/india/plugin.json``.
    """

    region_code = REGION_CODE

    def __init__(self) -> None:
        self._manifest_cache: "MarketRegion | None" = None

    def manifest(self) -> "MarketRegion":
        if self._manifest_cache is None:
            from utils.region_loader import get_market_region, load_market_regions

            region = get_market_region(REGION_CODE)
            if region is None:
                load_market_regions()
                region = get_market_region(REGION_CODE)
            if region is None:
                raise RuntimeError(
                    "IndiaRegionPlugin requires market_regions/india/plugin.json "
                    "to be loadable; the loader returned no region"
                )
            self._manifest_cache = region
        return self._manifest_cache

    def timezone_object(self) -> "tzinfo":
        return IST

    def holiday_calendar(self, year: int) -> list[dict[str, Any]]:
        if year != 2026:
            # Phase 2 relocated only the 2026 calendar. Future years
            # land in additional HOLIDAYS_<year> tables in
            # market_regions/india/holidays.py; this stub returns an
            # empty list so callers fail soft on future years.
            return []
        return [_coerce_holiday_to_seed(h, year) for h in HOLIDAYS_2026]

    def session_templates(self) -> list[Any]:
        return list(self.manifest().session_templates)

    def squareoff_rules(self) -> list[dict[str, Any]]:
        return [dict(rule) for rule in MANDATORY_CLOSE_RULES]

    def qty_freeze_rules(self) -> list[dict[str, Any]]:
        return [dict(rule) for rule in QUANTITY_FREEZE_RULES]

    def options_grammar(self) -> dict[str, Any]:
        # Return a deep copy of the aggregate dict so callers can
        # mutate freely without affecting the source-of-truth tables.
        out: dict[str, Any] = dict(_INDIA_OPTION_GRAMMAR)
        out["right_codes"] = dict(_INDIA_OPTION_GRAMMAR["right_codes"])
        out["lot_sizes"] = dict(_INDIA_OPTION_GRAMMAR["lot_sizes"])
        out["index_classification"] = {
            k: list(v) for k, v in _INDIA_OPTION_GRAMMAR["index_classification"].items()
        }
        return out

    def index_classification(self) -> dict[str, list[str]]:
        return {k: list(v) for k, v in _INDIA_INDEX_CLASSIFICATION.items()}

    def locale(self) -> dict[str, Any]:
        return dict(INDIAN_CURRENCY_LOCALE)

    def settlement_template(self, venue: str) -> str:
        # All India venues currently settle T+1 (post-Jan 2023 SEBI
        # rule). Read from the manifest if a specific venue carries an
        # override.
        v = (venue or "").strip().upper()
        for entry in self.manifest().venues:
            if entry.venue_code.upper() == v:
                return entry.settlement_template or "T+1"
        return "T+1"

    def sandbox_provider(self) -> Any:
        from services.sandbox.dispatcher import get_sandbox_provider

        return get_sandbox_provider(REGION_CODE)

    def options_provider(self) -> Any:
        from services.options.dispatcher import get_options_provider

        return get_options_provider(REGION_CODE)

    def screener_providers(self) -> list[str]:
        # India ships chartink as a screener provider. The list is
        # authoritative for callers that want to know which screener
        # codes are registered for India.
        return ["chartink"]


__all__ = ["IndiaRegionPlugin", "REGION_CODE"]
