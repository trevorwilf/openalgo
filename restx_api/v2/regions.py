"""GET /api/v2/regions — region plugin metadata.

Phase 5: surfaces the schema-v2 region plugins (venues, session
templates, symbol display, feature flags) so the frontend can
hydrate region-aware behavior without touching the legacy India
endpoints.

* ``GET /api/v2/regions`` — list every loaded region.
* ``GET /api/v2/regions/<region_code>`` — full region metadata.
* ``GET /api/v2/regions/<region_code>/flow_defaults`` — defaults the
  Flow Builder uses (exchanges, products, option underlyings,
  schedule). India returns the live Indian template; other regions
  return their own defaults from the plugin (or empty when the
  region's feature flag is off).
* ``GET /api/v2/regions/<region_code>/holidays?year=YYYY`` — holiday
  calendar (T-14 v7 Phase 3). Reads from the region plugin's
  ``calendar_exceptions`` and the optional RegionPlugin
  ``holiday_calendar(year)`` method. India v1
  ``/market/holidays`` remains mounted during the operator-
  controlled sunset window — non-India brokers MUST use the v2
  endpoint.
"""

from __future__ import annotations

from datetime import date
from typing import Any

from flask import request
from flask_restx import Namespace, Resource

from restx_api.v2._auth import error, ok

api = Namespace("regions", description="Market-region metadata (read-only)")


def _region_to_dict(region) -> dict[str, Any]:
    return region.model_dump(mode="json")


@api.route("")
@api.route("/")
class Regions(Resource):
    def get(self):
        from utils.region_loader import load_market_regions

        regions = load_market_regions()
        return ok({
            "regions": [_region_to_dict(r) for r in regions.values()],
        }), 200


@api.route("/<string:region_code>")
class RegionDetail(Resource):
    def get(self, region_code: str):
        from utils.region_loader import get_market_region

        region = get_market_region(region_code)
        if region is None:
            return error(
                "region_not_found",
                f"region {region_code!r} is not installed",
            ), 404
        return ok(_region_to_dict(region)), 200


@api.route("/<string:region_code>/holidays")
class RegionHolidays(Resource):
    """T-14 (v7 Phase 3) — region-dispatched holiday calendar.

    Replaces the India-only ``/api/v1/market/holidays`` for non-
    India brokers. The legacy v1 endpoint stays mounted (India
    deployments use it; sunset window is operator-controlled) but
    new code SHOULD prefer this v2 endpoint.

    Query params:
      * ``year`` — optional, integer; defaults to current year.

    Response shape:
        {
          "status": "success",
          "data": {
            "region_code": "<code>",
            "year": <int>,
            "holidays": [...]   # CalendarExceptionSeed-shaped
          }
        }
    """

    def get(self, region_code: str):
        from utils.region_loader import get_market_region

        region = get_market_region(region_code)
        if region is None:
            return error(
                "region_not_found",
                f"region {region_code!r} is not installed",
            ), 404

        # Resolve year from query param; default to current year.
        year_raw = request.args.get("year")
        if year_raw is None:
            year = date.today().year
        else:
            try:
                year = int(year_raw)
            except (TypeError, ValueError):
                return error(
                    "bad_request", "year must be an integer"
                ), 400

        # Prefer the RegionPlugin protocol's holiday_calendar(year)
        # if the region package ships one. Falls through to the
        # plugin.json calendar_exceptions filtered by year.
        holidays: list[Any] = []
        try:
            from utils.region_loader import get_region_plugin

            plugin = get_region_plugin(region_code)
        except Exception:
            plugin = None

        if plugin is not None and hasattr(plugin, "holiday_calendar"):
            try:
                exceptions = plugin.holiday_calendar(year)
                holidays = [
                    e.model_dump(mode="json") if hasattr(e, "model_dump") else e
                    for e in exceptions
                ]
            except Exception:
                holidays = []

        if not holidays and getattr(region, "calendar_exceptions", None):
            for exc in region.calendar_exceptions:
                exc_date = getattr(exc, "exception_date", None)
                if exc_date is not None and exc_date.year == year:
                    holidays.append(exc.model_dump(mode="json"))

        return ok({
            "region_code": region.region_code,
            "year": year,
            "holidays": holidays,
        }), 200


@api.route("/<string:region_code>/flow_defaults")
class RegionFlowDefaults(Resource):
    def get(self, region_code: str):
        from utils.region_loader import get_market_region

        region = get_market_region(region_code)
        if region is None:
            return error(
                "region_not_found",
                f"region {region_code!r} is not installed",
            ), 404

        flow_enabled = region.is_feature_enabled("flow_templates_enabled")
        if not flow_enabled:
            return ok({
                "region_code": region.region_code,
                "flow_templates_enabled": False,
                "exchanges": [],
                "products": [],
                "option_underlyings": [],
                "lot_sizes": {},
                "schedule_default": None,
            }), 200

        # Region-specific flow defaults come from the plugin's
        # ``metadata.flow_defaults`` block — this keeps India-specific
        # product strings out of Python source (ADR 0006 literal
        # scanner) and lets a future region declare its own products
        # without code changes.
        flow_defaults = (region.metadata or {}).get("flow_defaults", {})
        products = list(flow_defaults.get("products", []))
        return ok({
            "region_code": region.region_code,
            "flow_templates_enabled": True,
            "exchanges": list(region.default_venue_codes),
            "products": products,
            "option_underlyings": list(region.symbol_display.example_underlyings),
            "lot_sizes": {},  # populated dynamically by master_contract
            "schedule_default": {
                "timezone_name": region.timezone_name,
                "venue_code": region.default_venue_codes[0] if region.default_venue_codes else None,
            },
        }), 200
