"""Helpers for the market-region plugin framework.

This service layer keeps region-loading, broker capability metadata, and
persistent settings in one place so blueprints do not need to manually
compose three different subsystems.
"""

from __future__ import annotations

from typing import Any

from database.settings_db import get_default_market_region, set_default_market_region
from utils.plugin_loader import get_broker_capabilities
from utils.region_loader import get_market_region, load_market_regions

FALLBACK_REGION_CODE = "india"


def _fallback_region_code(regions: dict[str, Any]) -> str | None:
    if not regions:
        return None
    if FALLBACK_REGION_CODE in regions:
        return FALLBACK_REGION_CODE
    return next(iter(regions.keys()))


def resolve_default_market_region_code() -> str | None:
    """Return a valid stored default region code, with deterministic fallback."""
    regions = load_market_regions()
    configured = get_default_market_region()
    if configured in regions:
        return configured
    return _fallback_region_code(regions)


def get_default_market_region_details() -> dict[str, Any] | None:
    code = resolve_default_market_region_code()
    if not code:
        return None
    region = get_market_region(code)
    if region is None:
        return None
    return region.model_dump(mode="json")


def get_market_region_catalog(active_broker: str | None = None) -> dict[str, Any]:
    """Return all installed market regions plus active-broker compatibility."""
    regions = load_market_regions()
    default_region = resolve_default_market_region_code()
    broker_caps = get_broker_capabilities(active_broker) if active_broker else None
    supported_regions = set(broker_caps.supported_regions) if broker_caps else None

    entries: list[dict[str, Any]] = []
    for code, region in regions.items():
        payload = region.model_dump(mode="json")
        payload["is_default"] = code == default_region
        payload["supported_by_active_broker"] = (
            None if supported_regions is None else code in supported_regions
        )
        entries.append(payload)

    return {
        "default_region": default_region,
        "default_region_details": get_default_market_region_details(),
        "regions": entries,
        "active_broker": active_broker,
        "active_broker_supported_regions": (
            sorted(supported_regions) if supported_regions is not None else None
        ),
    }


def update_default_market_region(
    region_code: str, *, active_broker: str | None = None
) -> dict[str, Any]:
    """Persist a new default market region after validating it exists."""
    normalized = str(region_code).strip().lower().replace("-", "_")
    if not normalized:
        raise ValueError("region_code is required")

    regions = load_market_regions()
    region = regions.get(normalized)
    if region is None:
        available = ", ".join(sorted(regions.keys())) or "none"
        raise ValueError(
            f"Unknown market region {region_code!r}. Available market regions: {available}."
        )

    set_default_market_region(normalized)
    catalog = get_market_region_catalog(active_broker=active_broker)
    catalog["message"] = f"Default market region updated to {region.display_name}."
    return catalog


__all__ = [
    "get_default_market_region_details",
    "get_market_region_catalog",
    "resolve_default_market_region_code",
    "update_default_market_region",
]
