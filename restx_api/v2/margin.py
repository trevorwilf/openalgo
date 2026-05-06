"""POST /api/v2/margin — region-gated margin calculator.

The v1 margin calculator (services.margin_service.calculate_margin) is
India-shaped: it returns rupee margin for NSE/BSE/NFO/BFO/MCX baskets
and references SEBI margin slabs. ADR 0023 schedules a provider-
pluggable margin contract (currency-aware, venue-aware) but no non-
India provider is registered today.

Non-India regions get a structured 422 with the stable
``unsupported_capability`` error code; India calls fall through to the
existing service so the v2 surface matches v1 behavior bit-for-bit.
"""
from __future__ import annotations

from flask import request
from flask_restx import Namespace, Resource

from domain.errors import ErrorCode
from restx_api.v2._auth import error, ok, resolve_auth
from services.feature_gate_service import (
    active_region_code,
    is_india_region_active,
)
from utils.logging import get_logger

logger = get_logger(__name__)

api = Namespace("margin", description="Margin calculator (India only today)")


@api.route("")
@api.route("/")
class MarginV2(Resource):
    def post(self):
        auth_token, broker, auth_err = resolve_auth()
        if auth_err is not None:
            return error("unauthorized", auth_err), 401

        if not is_india_region_active():
            try:
                region = active_region_code()
            except Exception:
                region = "unknown"
            return error(
                ErrorCode.UNSUPPORTED_CAPABILITY,
                (
                    "margin calculator is currently India-only; ADR 0023 "
                    "schedules a provider-pluggable margin contract."
                ),
                details={
                    "active_region": region,
                    "dimension": "margin",
                },
            ), 422

        try:
            from services.margin_service import calculate_margin
        except ImportError as e:
            logger.exception("margin_service import failed: %s", e)
            return error("provider_error", "margin_service unavailable"), 502

        body = request.get_json(silent=True) or {}
        try:
            success, payload, status = calculate_margin(
                margin_data=body, api_key=body.get("apikey"),
            )
        except Exception as e:
            logger.exception("calculate_margin failed: %s", e)
            return error("provider_error", str(e)), 502

        if not success:
            return error(
                payload.get("code") or "provider_error",
                payload.get("message") or "margin calculation failed",
                details=payload,
            ), status or 502

        return ok({"region_code": "india", "margin": payload}), 200
