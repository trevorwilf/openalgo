"""Phase 6 — service-layer region feature gating.

Complements ``utils.capability_guards.@requires_capability``: that
decorator handles per-route gating; this service handles per-region
feature gating used INSIDE service code (option_chain_service,
flow_executor_service, sandbox/order_manager, etc.).

Active region resolution order:

1. The active broker's ``BrokerCapabilities.supported_regions[0]``
   (the broker plugin's primary region).
2. The user's stored ``settings.default_market_region``.
3. ``"india"`` as final fallback so legacy installs continue to
   resolve to the existing behavior.

Resolution is best-effort: missing Flask app context, missing broker
session, or missing settings rows all fall through to the fallback.
"""

from __future__ import annotations

from utils.logging import get_logger

logger = get_logger(__name__)

_FALLBACK_REGION = "india"


def active_region_code() -> str:
    """Return the active region code per the resolution order above."""
    # Test-only override — short-circuits everything.
    import os

    forced = os.environ.get("MARKET_REGION_FOR_TESTS")
    if forced:
        return forced.strip().lower()

    # 1. Per-broker primary region.
    broker = _current_broker_session_value()
    if broker:
        try:
            from utils.plugin_loader import get_broker_capabilities

            caps = get_broker_capabilities(broker)
        except Exception:
            caps = None
        if caps is not None:
            regions = list(caps.supported_regions or [])
            if regions:
                return str(regions[0]).strip().lower()

    # 2. Settings default.
    try:
        from services.market_region_service import resolve_default_market_region_code

        configured = resolve_default_market_region_code()
        if configured:
            return str(configured).strip().lower()
    except Exception as e:  # pragma: no cover - defensive
        logger.debug("default region lookup failed: %s", e)

    # 3. Fallback.
    return _FALLBACK_REGION


def is_india_region_active() -> bool:
    return active_region_code() == "india"


def is_feature_enabled_for_active_region(flag: str, default: bool = False) -> bool:
    """Look up a feature flag for the currently active region.

    Returns ``default`` when the region or the flag is missing.
    Reads the flag from the region plugin's ``feature_flags`` block
    (Phase 2 schema v2).
    """
    code = active_region_code()
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


__all__ = [
    "active_region_code",
    "is_feature_enabled_for_active_region",
    "is_india_region_active",
]
