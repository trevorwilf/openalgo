"""Service-layer region feature gating.

Complements ``utils.capability_guards.@requires_capability``: that
decorator handles per-route gating; this service handles per-region
feature gating used INSIDE service code (option_chain_service,
flow_executor_service, sandbox/order_manager, etc.).

Active region resolution order:

1. The active broker's ``BrokerCapabilities.supported_regions[0]``
   (the broker plugin's primary region).
2. The user's stored ``settings.default_market_region``.
3. The explicit legacy-India compatibility path (only when the caller
   passes ``legacy_india_fallback=True``).

If neither (1) nor (2) yields a region AND the caller has not opted
into the legacy India fallback, ``active_region_code`` raises
``RegionResolutionError`` (ADR 0023 invariant 1). Phase 2 of v4
removed the silent ``_FALLBACK_REGION = "india"`` constant; missing
region context is now a structured error in promoted code.

The two callers in this module — ``is_india_region_active`` and
``is_feature_enabled_for_active_region`` — pass
``legacy_india_fallback=True`` because they are the explicit, named
region gate used by services that have not yet migrated to provider-
pluggable dispatch (Sandbox until v4 Phase 8; Options until Phase 9;
Screeners until Phase 10).
"""

from __future__ import annotations

from utils.logging import get_logger

logger = get_logger(__name__)


def active_region_code(*, legacy_india_fallback: bool = False) -> str:
    """Return the active region code per the resolution order above.

    Parameters
    ----------
    legacy_india_fallback:
        When ``True`` and no broker / settings region is resolvable,
        the function returns ``"india"`` for the explicit legacy India
        compatibility path. When ``False`` (the v4 default), the same
        situation raises :class:`domain.errors.RegionResolutionError`.

    The two named callers in this module (:func:`is_india_region_active`
    and :func:`is_feature_enabled_for_active_region`) opt into the
    legacy fallback because they are the named region gate used by
    services that have not yet migrated to provider-pluggable
    dispatch.
    """
    # Test-only override — short-circuits everything.
    import os

    forced = os.environ.get("MARKET_REGION_FOR_TESTS")
    if forced:
        return forced.strip().lower()

    attempted_sources: list[str] = []

    # 1. Per-broker primary region.
    broker = _current_broker_session_value()
    if broker:
        attempted_sources.append(f"broker:{broker}")
        try:
            from utils.plugin_loader import get_broker_capabilities

            caps = get_broker_capabilities(broker)
        except Exception:
            caps = None
        if caps is not None:
            regions = list(getattr(caps, "supported_regions", None) or [])
            if regions:
                return str(regions[0]).strip().lower()

    # 2. Settings default.
    attempted_sources.append("settings.default_market_region")
    try:
        from services.market_region_service import resolve_default_market_region_code

        configured = resolve_default_market_region_code()
        if configured:
            return str(configured).strip().lower()
    except Exception as e:  # pragma: no cover - defensive
        logger.debug("default region lookup failed: %s", e)

    # 3. Either return the legacy India fallback (named callers opt
    # in) or raise the structured error (promoted code).
    if legacy_india_fallback:
        return _legacy_india_region_for_compat()

    from domain.errors import RegionResolutionError

    raise RegionResolutionError(attempted_sources=attempted_sources)


def _legacy_india_region_for_compat() -> str:
    """Return ``"india"`` for the explicit legacy India compatibility path.

    Wrapped in a single named function so every call-site is greppable
    and the deprecation can be tracked. Phase 8 (Sandbox), Phase 9
    (Options), and Phase 10 (Screeners) of v4 each remove one batch of
    callers; once provider-pluggable dispatch covers every advanced
    feature, this helper itself can be deprecated.
    """
    return "india"


def is_india_region_active() -> bool:
    """Named region gate — returns ``True`` when the active region is
    India. Uses the legacy India compatibility fallback so this
    function never raises; intended for the explicit, named region
    branch in services that have not yet migrated to provider-
    pluggable dispatch.
    """
    return active_region_code(legacy_india_fallback=True) == "india"


def is_feature_enabled_for_active_region(flag: str, default: bool = False) -> bool:
    """Look up a feature flag for the currently active region.

    Returns ``default`` when the region or the flag is missing.
    Reads the flag from the region plugin's ``feature_flags`` block
    (Phase 2 schema v2).

    Uses the legacy India compatibility fallback so this function
    never raises.
    """
    code = active_region_code(legacy_india_fallback=True)
    try:
        from services.market_region_service import is_region_feature_enabled

        return is_region_feature_enabled(code, flag, default=default)
    except Exception as e:  # pragma: no cover - defensive
        logger.debug("feature flag lookup failed: %s", e)
        return default


def _current_broker_session_value() -> str | None:
    """Return the active broker code from Flask session, or None.

    Falls back to None outside Flask context (CLI / tests). Tests can
    override by setting the ``MARKET_REGION_FOR_TESTS`` env var which
    short-circuits the entire chain.
    """
    import os

    forced = os.environ.get("MARKET_REGION_FOR_TESTS")
    if forced:
        # If the test forces a region, signal "no broker so the env
        # short-circuit kicks in". The active_region_code() function
        # then drops into the settings lookup, which honors the env
        # via market_region_service.
        return None

    try:
        from flask import session

        return session.get("broker")
    except Exception:
        return None


def require_region_feature(flag: str, error_code: str, *, message: str | None = None) -> None:
    """Raise ``FeatureNotAvailableInRegion`` when ``flag`` is disabled
    for the active region.

    Phase 4 v3 helper used at the entry point of India-shaped service
    functions (option_chain, iv_chart, gex, etc.) to fail fast for
    non-India regions instead of producing wrong results.
    """
    from domain.errors import FeatureNotAvailableInRegion

    if is_feature_enabled_for_active_region(flag, default=False):
        return
    region = active_region_code(legacy_india_fallback=True)
    raise FeatureNotAvailableInRegion(
        active_region=region,
        code=error_code,
        message=(
            message
            or f"feature {flag!r} is disabled in region {region!r}"
        ),
    )


__all__ = [
    "active_region_code",
    "is_feature_enabled_for_active_region",
    "is_india_region_active",
    "require_region_feature",
]
