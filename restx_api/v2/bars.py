"""POST /api/v2/bars — normalized OHLCV history."""

from __future__ import annotations

from typing import Any

from flask import request
from flask_restx import Namespace, Resource

from restx_api.v2._auth import error, ok, resolve_auth
from restx_api.v2.quotes import _resolve_ref
from utils.logging import get_logger

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

        resolved = _resolve_ref(ref, broker_code=broker)
        if resolved is None:
            return error(
                "instrument_not_resolvable",
                "instrument ref could not be resolved",
            ), 400

        from services.history_service import get_history_with_auth

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

        # v1 returns rows with keys: timestamp, open, high, low, close, volume, oi.
        # v2 adds the instrument envelope and normalizes the shape.
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
