"""POST /api/v2/bars — promoted-lane dispatch with legacy fallback.

Promoted path (``API_V2_<BROKER>=1`` + registered bar adapter):
dispatches via :class:`~domain.broker_market_data.BrokerBarAdapter`.
The legacy ``services.history_service`` is never loaded on this path.
"""

from __future__ import annotations

from dataclasses import asdict
from datetime import datetime
from typing import Any

from flask import request
from flask_restx import Namespace, Resource

from restx_api.v2._auth import error, ok, resolve_auth
from services.broker_market_data_registry import get_broker_bar_adapter
from utils.feature_flags import is_enabled
from utils.logging import get_logger
from utils.logging_context import log_context
from utils.metrics import counter

logger = get_logger(__name__)

api = Namespace("bars", description="Normalized OHLCV history")


@api.route("")
@api.route("/")
class Bars(Resource):
    def post(self):
        auth_token, broker, auth_err = resolve_auth()
        if auth_err is not None:
            return error("unauthorized", auth_err), 401

        body = request.get_json(silent=True) or {}
        ref = body.get("instrument")
        interval = body.get("interval")
        start = body.get("start")
        end = body.get("end")
        if not (ref and interval and start and end):
            return error(
                "bad_request",
                "body must include `instrument`, `interval`, `start`, `end`",
            ), 400

        broker_upper = (broker or "").upper()
        flag_on = is_enabled(f"API_V2_{broker_upper}")
        promoted = get_broker_bar_adapter(broker) if flag_on else None
        if promoted is not None:
            with log_context(broker_code=broker, legacy_fallback=False):
                return _dispatch_promoted(
                    ref, interval=interval, start=start, end=end,
                    broker=broker, auth_token=auth_token, adapter=promoted,
                )
        if flag_on:
            counter("promoted_legacy_fallback_total", {"broker": broker or "unknown"})
        with log_context(broker_code=broker, legacy_fallback=True):
            return _dispatch_legacy(
                ref, interval=interval, start=start, end=end,
                broker=broker, auth_token=auth_token,
            )


def _dispatch_promoted(
    raw_ref: Any, *, interval: str, start: Any, end: Any,
    broker: str, auth_token: str, adapter,
):
    from domain.broker_market_data import NormalizedBarRequest
    from domain.errors import UnsupportedCapability
    from restx_api.v2.quotes import _coerce_to_ref
    from services.instrument_resolution import resolve_instrument
    from pydantic import ValidationError as PydValidationError

    try:
        ref = _coerce_to_ref(raw_ref)
    except (PydValidationError, ValueError) as e:
        return error("bad_request", f"invalid instrument ref: {e}"), 400

    resolved = resolve_instrument(ref, broker_code=broker)
    if resolved is None:
        return error(
            "instrument_not_resolvable",
            "ref not found in instrument universe",
        ), 404

    try:
        start_dt = _parse_dt(start)
        end_dt = _parse_dt(end)
    except ValueError as e:
        return error("bad_request", f"bad datetime: {e}"), 400

    req = NormalizedBarRequest(interval=interval, start=start_dt, end=end_dt)
    account_ctx: dict[str, Any] = {"broker_code": broker, "auth_token": auth_token}

    try:
        bars = adapter.get_bars(resolved, req, account_ctx)
    except UnsupportedCapability as e:
        return error("unsupported_capability", str(e), details={
            "broker_code": e.broker_code,
            "capability_name": e.capability_name,
        }), 422

    return ok({
        "instrument": {
            "instrument_id": str(resolved.instrument_id),
            "venue_code": resolved.venue_code,
            "canonical_symbol": resolved.canonical_symbol,
        },
        "interval": interval,
        "bars": [_bar_to_dict(b) for b in bars],
    }), 200


def _bar_to_dict(b) -> dict[str, Any]:
    d = asdict(b)
    for k in ("open", "high", "low", "close", "volume"):
        if d.get(k) is not None:
            d[k] = str(d[k])
    if hasattr(b.ts, "isoformat"):
        d["ts"] = b.ts.isoformat()
    return d


def _parse_dt(val: Any) -> datetime:
    if isinstance(val, datetime):
        return val
    if isinstance(val, str):
        s = val.replace("Z", "+00:00")
        return datetime.fromisoformat(s)
    raise ValueError(f"expected ISO-8601 string or datetime, got {type(val).__name__}")


def _dispatch_legacy(
    ref: Any, *, interval: str, start: Any, end: Any,
    broker: str, auth_token: str,
):
    from restx_api.v2.quotes import _resolve_ref
    from services.history_service import get_history_with_auth

    resolved = _resolve_ref(ref, broker_code=broker)
    if resolved is None:
        return error(
            "instrument_not_resolvable",
            "instrument ref could not be resolved",
        ), 400

    ok_flag, resp, status = get_history_with_auth(
        auth_token=auth_token,
        feed_token=None,
        broker=broker,
        symbol=resolved["canonical_symbol"],
        exchange=resolved["venue_code"],
        interval=interval,
        start_date=start,
        end_date=end,
    )
    if not ok_flag:
        return error("broker_error", resp.get("message", "history fetch failed")), status

    rows = resp.get("data", [])
    return ok({
        "instrument": {
            "instrument_id": resolved.get("instrument_id"),
            "venue_code": resolved["venue_code"],
            "canonical_symbol": resolved["canonical_symbol"],
        },
        "interval": interval,
        "bars": rows,
    }), 200
