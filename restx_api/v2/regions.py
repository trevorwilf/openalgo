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
"""

from __future__ import annotations

from typing import Any

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
