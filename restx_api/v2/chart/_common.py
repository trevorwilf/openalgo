"""Shared helpers for the /api/v2/chart/* skeleton."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any

from flask import request

from database.auth_db import get_auth_token_broker
from restx_api.v2._auth import error, ok

__all__ = ["error", "ok", "parse_body", "resolve_user_id"]


def resolve_user_id() -> tuple[str | None, str | None]:
    """Resolve (user_id, error) for the current request.

    Phase 1 uses the API key string itself as the user-scope key; this
    is sufficient to make per-row scoping testable today and is replaced
    by a real user lookup in Phase 5 when CRUD is wired.
    """
    api_key = None
    if request.is_json:
        data = request.get_json(silent=True) or {}
        api_key = data.get("apikey")
    if not api_key:
        api_key = request.args.get("apikey") or request.headers.get("X-API-KEY")
    if not api_key:
        return None, "missing apikey"
    auth_token, _feed, broker = get_auth_token_broker(api_key, include_feed_token=True)
    if auth_token is None:
        return None, "invalid apikey"
    # Use the API key as the scope id; replace with username lookup in Phase 5.
    return f"u:{api_key[:12]}", None


def parse_body() -> dict[str, Any]:
    """Best-effort JSON body extraction; never raises."""
    return request.get_json(silent=True) or {}


def utcnow_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def safe_loads(s: str | None) -> Any:
    if s is None or s == "":
        return None
    try:
        return json.loads(s)
    except (TypeError, ValueError):
        return None
