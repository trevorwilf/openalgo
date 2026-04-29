"""Service-layer region feature gating.

Complements ``utils.capability_guards.@requires_capability``: that
decorator handles per-route gating; this service handles per-region
feature gating used INSIDE service code (option_chain_service,
flow_executor_service, sandbox/order_manager, etc.).

Active region resolution order:

1. The active broker's ``BrokerCapabilities.supported_regions[0]``
   (the broker plugin's primary region).
2. The user's stored ``settings.default_market_region``.

If neither (1) nor (2) yields a region, ``active_region_code``
raises ``RegionResolutionError`` (ADR 0023 invariant 1; ADR 0031 v6
Phase 4-bis closing). v6 Phase 4-bis retired the
``legacy_india_fallback`` parameter and the
``_legacy_india_region_for_compat`` helper that used to back step 3
of the resolution chain. Missing region context is now ALWAYS a
structured error in active_region_code; the named gates
(``is_india_region_active`` and
``is_feature_enabled_for_active_region``) catch the exception and
return ``False`` / the caller's ``default`` instead of silently
falling back to India.
"""

from __future__ import annotations

from utils.logging import get_logger

logger = get_logger(__name__)


def active_region_code() -> str:
    """Return the active region code per the resolution order above.

    v6 Phase 4-bis (ADR 0031): the ``legacy_india_fallback`` parameter
    has been retired. The function now ALWAYS raises
    :class:`domain.errors.RegionResolutionError` when no broker /
    settings region is resolvable. Named callers
    (:func:`is_india_region_active`,
    :func:`is_feature_enabled_for_active_region`,
    :func:`require_region_feature`) catch the exception and decide
    their own fallback semantics — by reading
    :class:`BrokerCapabilities` directly, not via a hidden literal
    fallback.
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

    # No broker, no settings, no env override → raise the structured
    # error. v6 Phase 4-bis retired the legacy India fallback that
    # used to live here.
    from domain.errors import RegionResolutionError

    raise RegionResolutionError(attempted_sources=attempted_sources)


def is_india_region_active() -> bool:
    """Named region gate — returns ``True`` when the active region is
    India.

    v6 Phase 4-bis (ADR 0031): capability-driven. Reads the active
    broker's :class:`BrokerCapabilities.supported_regions`; returns
    ``True`` iff ``"india"`` is in that list. Returns ``False`` when
    no broker is connected or the broker is not India-shaped — there
    is no longer a silent India fallback.

    Never raises.
    """
    try:
        return active_region_code() == "india"
    except Exception:
        # No broker, no settings, no env override → not India.
        return False


def is_feature_enabled_for_active_region(flag: str, default: bool = False) -> bool:
    """Look up a feature flag for the currently active region.

    Returns ``default`` when the region or the flag is missing.
    Reads the flag from the region plugin's ``feature_flags`` block
    (Phase 2 schema v2).

    v6 Phase 4-bis (ADR 0031): never raises — falls through to
    ``default`` when the region cannot be resolved.
    """
    try:
        code = active_region_code()
    except Exception:
        return default
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
    try:
        region = active_region_code()
    except Exception:
        # v6 Phase 4-bis: when no region resolves, surface "unknown"
        # rather than silently fall back to India. The caller's gate
        # is_feature_enabled_for_active_region already returned
        # False, so we know the feature is disabled regardless.
        region = "unknown"
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
