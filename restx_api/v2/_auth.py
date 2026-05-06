"""Shared auth + error helpers for /api/v2 endpoints.

Reuses the v1 auth mechanism (API key in the `apikey` field) so
operators do not manage two sets of credentials. Error envelope is
strictly typed — v2 errors carry `code` + `message` + `details`,
distinct from v1's `{"status": "error", "message": ...}` shape.
"""

from __future__ import annotations

from typing import Any, Dict, Optional, Tuple

from flask import request

from database.auth_db import get_auth_token_broker


def resolve_auth() -> Tuple[Optional[str], Optional[str], Optional[str]]:
    """Extract the API key from request and resolve (auth_token, broker).

    Returns (auth_token, broker, error_message). On success error is None.
    """
    api_key = None
    if request.is_json:
        data = request.get_json(silent=True) or {}
        api_key = data.get("apikey")
    if not api_key:
        api_key = request.args.get("apikey") or request.headers.get("X-API-KEY")
    if not api_key:
        return None, None, "missing apikey"

    auth_token, _feed, broker = get_auth_token_broker(api_key, include_feed_token=True)
    if auth_token is None:
        return None, None, "invalid apikey"
    return auth_token, broker, None


def error(code: str, message: str, *, details: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """v2 error envelope. Distinct from v1 error shape."""
    return {
        "error": {
            "code": code,
            "message": message,
            "details": details or {},
        }
    }


def ok(data: Any) -> Dict[str, Any]:
    """v2 success envelope."""
    return {"data": data}


def resolve_active_region_from_broker(broker: Optional[str]) -> str:
    """Return the active region code derived from a broker plugin.

    API-key-authenticated callers don't populate ``flask.session``, so
    ``services.feature_gate_service.is_india_region_active`` (which
    reads session) falls through to the settings default and reports
    "india" for non-India brokers like Alpaca. This helper bypasses
    the session reader and reads ``supported_regions[0]`` directly
    from the broker's plugin capabilities, matching the pattern
    already used by ``restx_api.v2.options._resolve_options_provider``.

    Returns ``"unknown"`` if the broker is missing or its plugin has
    no ``supported_regions`` declared.
    """
    if not broker:
        return "unknown"
    try:
        from utils.plugin_loader import get_broker_capabilities
        caps = get_broker_capabilities(broker)
    except Exception:
        return "unknown"
    regions = list(getattr(caps, "supported_regions", None) or [])
    if not regions:
        return "unknown"
    return str(regions[0]).strip().lower()
