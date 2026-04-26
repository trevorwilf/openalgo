"""Phase 2 v4 (ADR 0023, invariant 5) — v1 hard-block for non-India brokers.

The legacy ``/api/v1/*`` routes carry implicit India semantics in their
schemas (NSE/NFO/BSE exchange codes, MIS/CNC/NRML products, IST
timestamps, INR prices), their underlying services
(``services.place_order_service``, ``services.quotes_service``, etc.),
and their response shapes. Letting a non-India broker session reach
any of these routes is a correctness hazard.

This module provides a single guard helper invoked by every v1
blueprint via ``api_v1_bp.before_request``. The guard is fail-closed:

* If the active broker session resolves to a broker whose
  ``supported_regions`` includes ``"india"``, return None and the
  request proceeds.
* If the active broker is non-India, return a structured 410 Gone
  response with code ``v1_unavailable_for_non_india_broker``.
* If there is no broker session at all (first request before login),
  return None — the request will be rejected by the per-route auth
  layer with the existing 401 / API-key validation.
* If the broker capability cannot be loaded (e.g., disabled plugin),
  return None — the route's own validation handles the failure.

The guard is wired into ``restx_api/__init__.py`` so every v1 route
gets the check without per-file edits.
"""

from __future__ import annotations

from flask import jsonify, request

from utils.logging import get_logger

logger = get_logger(__name__)


def _active_broker() -> str | None:
    """Return the active broker code from Flask session (or None)."""
    try:
        from flask import session

        broker = session.get("broker")
        if broker:
            return str(broker).strip().lower() or None
    except Exception:
        pass
    return None


def _broker_supports_india(broker: str) -> bool | None:
    """Return True if the broker plugin's ``supported_regions`` includes
    ``"india"``; False if it does not; None if the capability cannot
    be loaded.
    """
    try:
        from utils.plugin_loader import get_broker_capabilities

        caps = get_broker_capabilities(broker)
    except Exception:  # pragma: no cover - defensive
        return None
    if caps is None:
        return None
    regions = list(getattr(caps, "supported_regions", None) or [])
    return any(str(r).strip().lower() == "india" for r in regions)


def enforce_india_only():
    """Flask ``before_request`` hook for the v1 blueprint.

    Returns ``None`` to let the request continue, or a Flask response
    tuple ``(json, 410)`` to short-circuit non-India brokers.
    """
    # Skip for swagger / openapi documentation endpoints — they are
    # introspection routes that don't carry trading semantics.
    path = request.path or ""
    if path.endswith("/swagger.json") or path.endswith("/swaggerui"):
        return None

    broker = _active_broker()
    if broker is None:
        # No session yet — let downstream auth decide (401).
        return None

    supports_india = _broker_supports_india(broker)
    if supports_india is None or supports_india:
        # Either an India-supporting broker, or unknown capability
        # (legacy plugin without explicit supported_regions). Allow
        # through — preserves bit-identical India behavior.
        return None

    from domain.errors import ErrorCode

    payload = {
        "status": "error",
        "code": ErrorCode.V1_UNAVAILABLE_FOR_NON_INDIA_BROKER,
        "message": (
            f"/api/v1 is not available for broker {broker!r} "
            "(non-India broker). Use /api/v2 for promoted-lane "
            "endpoints. See ADR 0023 (v4 invariant 5)."
        ),
        "details": {
            "broker_code": broker,
            "supported_regions": list(_supported_regions(broker)),
            "promoted_lane_root": "/api/v2",
        },
    }
    try:
        from utils.metrics import counter

        counter(
            "v1_unavailable_for_non_india_broker_total",
            {"broker": broker, "path": path},
        )
    except Exception:  # pragma: no cover
        pass
    logger.info(
        "v1 hard-block: non-India broker %r attempted %s; returning 410",
        broker,
        path,
    )
    return jsonify(payload), 410


def _supported_regions(broker: str) -> list[str]:
    try:
        from utils.plugin_loader import get_broker_capabilities

        caps = get_broker_capabilities(broker)
        if caps is None:
            return []
        return [str(r) for r in (getattr(caps, "supported_regions", None) or [])]
    except Exception:  # pragma: no cover
        return []
