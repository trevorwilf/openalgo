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


def _legacy_india_region_for_compat() -> str:
    """Return ``"india"`` for the explicit legacy India compatibility path.

    Phase 2 v4 (ADR 0023, invariant 1) replaced the silent
    ``FALLBACK_REGION_CODE = "india"`` constant with this single,
    named, deprecated wrapper. It is used only by
    :func:`_fallback_region_code` to decide which region to surface
    when settings are unconfigured AND the multi-region catalog
    happens to include India. Promoted code that resolves the active
    region calls
    :func:`services.feature_gate_service.active_region_code` (with
    ``legacy_india_fallback=False``) and gets a structured
    :class:`domain.errors.RegionResolutionError` instead.
    """
    return "india"


def _fallback_region_code(regions: dict[str, Any]) -> str | None:
    """Pick a deterministic region from the catalog when the operator
    has not configured one.

    Prefers India (legacy default) when present in the catalog; falls
    through to the first installed region otherwise. This helper is
    invoked only by :func:`resolve_default_market_region_code`, which
    is itself the *settings* lookup — not the per-request region
    resolver. Promoted per-request code uses
    :func:`services.feature_gate_service.active_region_code` and gets
    a structured error when nothing resolves.
    """
    if not regions:
        return None
    legacy_india = _legacy_india_region_for_compat()
    if legacy_india in regions:
        return legacy_india
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
    # Observability: surface region flips in metrics.
    try:
        from utils.metrics import counter

        counter("default_region_changes_total", {"region": normalized})
    except Exception:  # pragma: no cover
        pass
    catalog = get_market_region_catalog(active_broker=active_broker)
    catalog["message"] = f"Default market region updated to {region.display_name}."
    return catalog


def get_venue_seed(region_code: str, venue_code: str):
    """Return a ``VenueSeed`` from a region plugin, or ``None``.

    Schema-v2 accessor introduced in Phase 2. Region plugins that
    haven't been upgraded to v2 simply have an empty ``venues`` list,
    so this returns ``None`` for them — callers should treat absence
    as "fall back to legacy database/market_calendar_db."""
    region = get_market_region(region_code)
    if region is None:
        return None
    return region.get_venue(venue_code)


def get_session_templates(region_code: str, venue_code: str):
    """List session templates for a venue from the region plugin."""
    region = get_market_region(region_code)
    if region is None:
        return []
    return list(region.get_sessions_for(venue_code))


def get_symbol_display(region_code: str):
    """Return the region's ``SymbolDisplay`` (always non-None — empty
    when the plugin has no v2 ``symbol_display`` block)."""
    region = get_market_region(region_code)
    if region is None:
        from domain.regions import SymbolDisplay

        return SymbolDisplay()
    return region.symbol_display


def is_region_feature_enabled(
    region_code: str, flag: str, default: bool = False
) -> bool:
    """Check a region's feature flag. Returns ``default`` for missing
    region or missing flag."""
    region = get_market_region(region_code)
    if region is None:
        return default
    return region.is_feature_enabled(flag, default=default)


__all__ = [
    "get_default_market_region_details",
    "get_market_region_catalog",
    "get_session_templates",
    "get_symbol_display",
    "get_venue_seed",
    "is_region_feature_enabled",
    "resolve_default_market_region_code",
    "update_default_market_region",
]
