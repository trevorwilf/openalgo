"""POST /api/v2/quotes — batch normalized quote fetch."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from flask import request
from flask_restx import Namespace, Resource

from restx_api.v2._auth import error, ok, resolve_auth
from utils.logging import get_logger

logger = get_logger(__name__)

api = Namespace("quotes", description="Normalized quote fetch")


@api.route("")
@api.route("/")
class Quotes(Resource):
    def post(self):
        auth_token, broker, auth_err = resolve_auth()
        if auth_err is not None:
            return error("unauthorized", auth_err), 401

        body = request.get_json(silent=True) or {}
        refs = body.get("instruments")
        if not isinstance(refs, list) or not refs:
            return error(
                "bad_request", "body.instruments[] is required and must be non-empty"
            ), 400

        from services.quotes_service import get_quotes_with_auth

        out: list[dict[str, Any]] = []
        for raw_ref in refs:
            resolved = _resolve_ref(raw_ref, broker_code=broker)
            if resolved is None:
                # Include an error entry for this ref; do not short-circuit.
                out.append({
                    "instrument": raw_ref,
                    "error": {
                        "code": "instrument_not_resolvable",
                        "message": "ref could not be resolved",
                    },
                })
                continue

            ok_flag, resp, status = get_quotes_with_auth(
                auth_token=auth_token,
                feed_token=None,
                broker=broker,
                symbol=resolved["canonical_symbol"],
                exchange=resolved["venue_code"],
            )
            if not ok_flag:
                out.append({
                    "instrument": {
                        "instrument_id": resolved.get("instrument_id"),
                        "venue_code": resolved["venue_code"],
                        "canonical_symbol": resolved["canonical_symbol"],
                    },
                    "error": {
                        "code": "broker_error",
                        "message": resp.get("message", "quote fetch failed"),
                    },
                })
                continue

            payload = resp.get("data", {})
            out.append({
                "instrument": {
                    "instrument_id": resolved.get("instrument_id"),
                    "venue_code": resolved["venue_code"],
                    "canonical_symbol": resolved["canonical_symbol"],
                },
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "quote": payload,
            })
        return ok(out), 200


def _resolve_ref(raw: Any, broker_code: str | None) -> dict | None:
    """Best-effort ref resolution.

    Accepts both the normalized InstrumentRef shape and the legacy
    `{symbol, exchange}` shape. Always returns `venue_code` +
    `canonical_symbol` (both strings) so the legacy get_quotes path
    receives the same input it did pre-v2.
    """
    if not isinstance(raw, dict):
        return None
    # Shape 2: venue_symbol
    if raw.get("venue_code") and raw.get("canonical_symbol"):
        return {
            "venue_code": raw["venue_code"],
            "canonical_symbol": raw["canonical_symbol"],
            "instrument_id": raw.get("instrument_id"),
        }
    # Legacy {symbol, exchange}
    if raw.get("symbol") and raw.get("exchange"):
        return {
            "venue_code": raw["exchange"],
            "canonical_symbol": raw["symbol"],
            "instrument_id": None,
        }
    # Shape 1: instrument_id — look up canonical symbol/venue.
    if raw.get("instrument_id"):
        import uuid

        from database.instruments_repo import instruments_get_by_id

        try:
            uid = uuid.UUID(str(raw["instrument_id"]))
        except ValueError:
            return None
        inst = instruments_get_by_id(uid)
        if inst is None:
            return None
        return {
            "venue_code": inst.venue_code,
            "canonical_symbol": inst.canonical_symbol,
            "instrument_id": str(inst.instrument_id),
        }
    return None
