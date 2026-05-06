"""POST /api/v2/depth — promoted-lane Level 2 / market depth.

Documented Phase 8-bis migration target. Translator hook:
``get_depth_via_token(auth_token, instrument)`` returns a per-symbol
depth ladder ``{"bids": [{price, qty}, ...], "asks": [...], ...}``.

Capability boundary:
  * Alpaca's v2 stocks API exposes top-of-book only (best bid / best
    ask + sizes via ``/api/v2/quotes``). There is no Level 2 stream,
    so AlpacaOrderTranslator does NOT implement
    ``get_depth_via_token`` and this route returns
    ``501 unimplemented`` for an Alpaca session — the operator can
    fall back to ``/api/v2/quotes`` for top-of-book.
  * Indian broker translators (DhanHQ, Zerodha, etc.) are expected to
    implement the hook so this route returns real depth ladders.

Body shape:
  {"apikey": "...",
   "instruments": [{"venue_code": "...", "canonical_symbol": "..."}, ...]}
"""
from __future__ import annotations

from typing import Any

from flask import request
from flask_restx import Namespace, Resource

from restx_api.v2._auth import error, ok, resolve_auth
from services.broker_translator_registry import get_broker_translator
from utils.feature_flags import is_enabled
from utils.logging import get_logger

logger = get_logger(__name__)

api = Namespace("depth", description="Normalized market depth (L2)")


def _ensure_promoted(broker: str | None):
    if not broker:
        return None, error("bad_request", "broker not resolved from session"), 400
    flag_on = is_enabled(f"API_V2_{broker.upper()}")
    if not flag_on:
        return None, error(
            "promoted_lane_required",
            f"depth on /api/v2 requires API_V2_{broker.upper()}=1",
            details={"broker_code": broker},
        ), 503
    promoted = get_broker_translator(broker)
    if promoted is None:
        return None, error(
            "translator_not_registered",
            f"Promoted lane is enabled for broker {broker!r} but no "
            "BrokerOrderTranslator is registered.",
            details={"broker_code": broker, "flag": f"API_V2_{broker.upper()}"},
        ), 503
    return promoted, None, None


@api.route("")
@api.route("/")
class Depth(Resource):
    def post(self):
        auth_token, broker, auth_err = resolve_auth()
        if auth_err is not None:
            return error("unauthorized", auth_err), 401

        promoted, err_payload, err_status = _ensure_promoted(broker)
        if promoted is None:
            return err_payload, err_status

        fn = getattr(promoted, "get_depth_via_token", None)
        if not callable(fn):
            return error(
                "unimplemented",
                f"broker {broker!r} translator does not implement get_depth_via_token "
                "(Alpaca's v2 stocks API exposes top-of-book only — use /api/v2/quotes for best bid/ask)",
                details={"broker_code": broker,
                         "fallback_route": "/api/v2/quotes"},
            ), 501

        body = request.get_json(silent=True) or {}
        instruments = body.get("instruments")
        if not isinstance(instruments, list) or not instruments:
            return error(
                "bad_request",
                "body must include `instruments` (non-empty list)",
            ), 400

        from services.instrument_resolution import resolve_instrument
        from domain.instrument_ref import InstrumentRef
        from pydantic import ValidationError as PydValidationError

        out: list[dict[str, Any]] = []
        for i, raw in enumerate(instruments):
            try:
                ref = InstrumentRef(**raw)
            except PydValidationError as e:
                return error(
                    "validation_error",
                    f"instruments[{i}]: invalid ref",
                    details={"errors": e.errors()},
                ), 422
            resolved = resolve_instrument(ref, broker_code=broker)
            if resolved is None:
                out.append({
                    "instrument": raw,
                    "error": {"code": "instrument_not_resolvable"},
                })
                continue
            try:
                ladder = fn(auth_token, resolved)
            except RuntimeError as e:
                out.append({
                    "instrument": {
                        "instrument_id": str(resolved.instrument_id),
                        "venue_code": resolved.venue_code,
                        "canonical_symbol": resolved.canonical_symbol,
                    },
                    "error": {"code": "broker_error", "message": str(e)},
                })
                continue
            except Exception as e:  # noqa: BLE001
                logger.exception("get_depth_via_token failed: %s", e)
                out.append({
                    "instrument": {
                        "instrument_id": str(resolved.instrument_id),
                        "venue_code": resolved.venue_code,
                        "canonical_symbol": resolved.canonical_symbol,
                    },
                    "error": {"code": "broker_error", "message": str(e)},
                })
                continue
            out.append({
                "instrument": {
                    "instrument_id": str(resolved.instrument_id),
                    "venue_code": resolved.venue_code,
                    "canonical_symbol": resolved.canonical_symbol,
                },
                "depth": ladder,
            })

        return ok(out), 200
