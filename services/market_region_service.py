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


# ---------------------------------------------------------------------------
# Phase 3 (T-20) — region-aware vocabulary helpers.
#
# Replace promoted-lane consumers of ``utils.constants.VALID_EXCHANGES``
# / ``VALID_PRODUCT_TYPES`` / ``VALID_PRICE_TYPES`` with a single
# region-aware lookup. Each helper resolves the active region via
# :mod:`services.feature_gate_service` and reads from the manifest's
# venues / product_vocabulary / price_type_vocabulary fields (Phase 0
# T-01 schema). The active broker's region is the source of truth; no
# legacy India-fallback default. ADR 0006 invariant 5.
# ---------------------------------------------------------------------------


def _resolve_active_market_region():
    """Return the active region's :class:`MarketRegion` instance.

    Raises :class:`domain.errors.MissingRegionContext` when nothing
    resolvable is available — never silently defaults to India.
    """
    from domain.errors import MissingRegionContext, RegionResolutionError
    from services.feature_gate_service import active_region_code

    try:
        code = active_region_code()
    except RegionResolutionError as exc:
        raise MissingRegionContext(
            "active region could not be resolved; configure the broker "
            "session region or set settings.default_market_region",
            attempted_sources=getattr(exc, "attempted_sources", None) or [],
        ) from exc

    region = get_market_region(code)
    if region is None:
        # Lazy-load: in worker / CLI contexts the region cache may not
        # have been warmed by app startup. Re-scan once before failing.
        load_market_regions()
        region = get_market_region(code)
    if region is None:
        raise MissingRegionContext(
            f"active region {code!r} is not registered as a market "
            "region plugin; install the corresponding "
            "market_regions/<code>/ package",
            attempted_sources=[f"market_regions/{code}"],
        )
    return region


def get_allowed_venue_codes_for_active_region() -> list[str]:
    """Return the venue codes the active region accepts.

    Reads the union of:

    * Each :class:`VenueSeed` in ``region.venues``.
    * Any extra codes carried in
      ``region.legacy_compat_shim["valid_exchanges"]`` (for India
      compat: ``CRYPTO`` is not a real venue but a legacy classifier).

    The returned list preserves the order declared in
    ``legacy_compat_shim.valid_exchanges`` if present (so error
    messages list the venues in the same order they appeared in the
    legacy ``VALID_EXCHANGES`` list, keeping parity bit-identical with
    pre-Phase-3 messages).
    """
    region = _resolve_active_market_region()
    shim = region.legacy_compat_shim or {}
    declared_order = list(shim.get("valid_exchanges") or [])
    if declared_order:
        return declared_order
    # No legacy_compat_shim → derive from venues alone.
    return [v.venue_code for v in region.venues]


def get_allowed_product_codes_for_active_region() -> list[str]:
    """Return the union of all product codes across asset classes
    declared in the active region's ``product_vocabulary`` (Phase 0
    T-01 schema field). The ``ALL`` key is preferred as the canonical
    flat list when present; otherwise the union of every value list."""
    from domain.errors import MissingRegionContext

    region = _resolve_active_market_region()
    vocab = region.product_vocabulary or {}
    if "ALL" in vocab:
        return list(vocab["ALL"])
    if not vocab:
        raise MissingRegionContext(
            f"region {region.region_code!r} has no product_vocabulary "
            "declared; the manifest must populate "
            "product_vocabulary.ALL or per-asset-class lists before "
            "promoted-lane order services can validate against it",
            attempted_sources=[f"market_regions/{region.region_code}/plugin.json"],
        )
    seen: list[str] = []
    for values in vocab.values():
        for v in values or ():
            if v not in seen:
                seen.append(v)
    return seen


def get_allowed_price_type_codes_for_active_region() -> list[str]:
    """Return the union of all price-type codes declared in the active
    region's ``price_type_vocabulary``. ``ALL`` key takes precedence."""
    from domain.errors import MissingRegionContext

    region = _resolve_active_market_region()
    vocab = region.price_type_vocabulary or {}
    if "ALL" in vocab:
        return list(vocab["ALL"])
    if not vocab:
        raise MissingRegionContext(
            f"region {region.region_code!r} has no price_type_vocabulary "
            "declared; the manifest must populate "
            "price_type_vocabulary.ALL or per-asset-class lists before "
            "promoted-lane order services can validate against it",
            attempted_sources=[f"market_regions/{region.region_code}/plugin.json"],
        )
    seen: list[str] = []
    for values in vocab.values():
        for v in values or ():
            if v not in seen:
                seen.append(v)
    return seen


def get_allowed_action_codes_for_active_region() -> list[str]:
    """Return the action codes (BUY/SELL) the active region accepts.

    Currently sourced from ``legacy_compat_shim.valid_actions``;
    long-term this becomes a first-class ``MarketRegion.action_vocabulary``
    field. The compat-shim location keeps Phase 3 a pure migration from
    ``utils.constants.VALID_ACTIONS`` without a second schema change.
    """
    region = _resolve_active_market_region()
    shim = region.legacy_compat_shim or {}
    actions = list(shim.get("valid_actions") or [])
    if actions:
        return actions
    return ["BUY", "SELL"]


__all__ = [
    "get_allowed_action_codes_for_active_region",
    "get_allowed_price_type_codes_for_active_region",
    "get_allowed_product_codes_for_active_region",
    "get_allowed_venue_codes_for_active_region",
    "get_default_market_region_details",
    "get_market_region_catalog",
    "get_session_templates",
    "get_symbol_display",
    "get_venue_seed",
    "is_region_feature_enabled",
    "resolve_default_market_region_code",
    "update_default_market_region",
]
