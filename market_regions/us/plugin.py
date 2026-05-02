"""USRegionPlugin — composes the US data modules into a
:class:`domain.region_plugin.RegionPlugin` instance.

Phase 7b parallels ``market_regions.india.plugin.IndiaRegionPlugin``
but for the US market. Behavior is intentionally mock-grade for the
sandbox / framework-readiness path; real US trading requires a real
broker plugin (Schwab, Webull, Alpaca, etc. — see
:doc:`docs/refactor/future-broker-onboarding-checklist.md`).
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from market_regions.us.holidays import HOLIDAYS_BY_YEAR
from market_regions.us.locale import US_CURRENCY_LOCALE
from market_regions.us.options_grammar import (
    INDEX_CLASSIFICATION as _US_INDEX_CLASSIFICATION,
)
from market_regions.us.options_grammar import OPTION_GRAMMAR as _US_OPTION_GRAMMAR
from market_regions.us.qty_freeze import QUANTITY_FREEZE_RULES
from market_regions.us.sessions import US_EASTERN
from market_regions.us.settlement import SETTLEMENT_BY_INSTRUMENT_KIND
from market_regions.us.squareoff import MANDATORY_CLOSE_RULES

if TYPE_CHECKING:  # pragma: no cover
    from datetime import tzinfo

    from domain.regions import MarketRegion


REGION_CODE: str = "us"


class USRegionPlugin:
    """:class:`RegionPlugin` implementation for the United States.

    Region-data accessors return deep copies so callers can mutate
    freely. Provider accessors delegate to the global dispatchers
    (already auto-installed at import time per the dispatcher
    modules).
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
                    "USRegionPlugin requires market_regions/us/plugin.json "
                    "to be loadable; the loader returned no region"
                )
            self._manifest_cache = region
        return self._manifest_cache

    def timezone_object(self) -> "tzinfo":
        return US_EASTERN

    def holiday_calendar(self, year: int) -> list[dict[str, Any]]:
        entries = HOLIDAYS_BY_YEAR.get(year, [])
        return [dict(h) for h in entries]

    def session_templates(self) -> list[Any]:
        return list(self.manifest().session_templates)

    def squareoff_rules(self) -> list[dict[str, Any]]:
        return [dict(rule) for rule in MANDATORY_CLOSE_RULES]

    def qty_freeze_rules(self) -> list[dict[str, Any]]:
        return [dict(rule) for rule in QUANTITY_FREEZE_RULES]

    def options_grammar(self) -> dict[str, Any]:
        out: dict[str, Any] = dict(_US_OPTION_GRAMMAR)
        out["right_codes"] = dict(_US_OPTION_GRAMMAR["right_codes"])
        out["index_classification"] = {
            k: list(v) for k, v in _US_OPTION_GRAMMAR["index_classification"].items()
        }
        return out

    def index_classification(self) -> dict[str, list[str]]:
        return {k: list(v) for k, v in _US_INDEX_CLASSIFICATION.items()}

    def locale(self) -> dict[str, Any]:
        return dict(US_CURRENCY_LOCALE)

    def settlement_template(self, venue: str) -> str:
        v = (venue or "").strip().upper()
        for entry in self.manifest().venues:
            if entry.venue_code.upper() == v:
                return entry.settlement_template or "T+1"
        # Fallback to instrument-kind-based lookup (callers that pass
        # an instrument family code rather than a venue code).
        return SETTLEMENT_BY_INSTRUMENT_KIND.get(v, "T+1")

    def sandbox_provider(self) -> Any:
        from services.sandbox.dispatcher import get_sandbox_provider

        return get_sandbox_provider(REGION_CODE)

    def options_provider(self) -> Any:
        from services.options.dispatcher import get_options_provider

        return get_options_provider(REGION_CODE)

    def screener_providers(self) -> list[str]:
        # No US screener provider ships in this repo. The slot is
        # registered (services/screeners/providers/us/__init__.py
        # exists) but every screener method raises NotImplementedError.
        # Future engagements may add a TradingView screener webhook.
        return []


__all__ = ["REGION_CODE", "USRegionPlugin"]
