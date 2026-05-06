"""POST /api/v2/pnl/symbols — region-gated day-P&L breakdown.

The v1 ``/api/v1/pnl/symbols`` endpoint reads sandbox-mode positions
through ``services.sandbox_service.sandbox_get_pnl_symbols``; per
ADR 0004 the analyzer/sandbox is India-only and per ADR 0023 the
sandbox is provider-pluggable. Until non-India sandbox providers ship
day-PnL adapters the v2 route gates non-India regions with a
structured 422.
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

api = Namespace("pnl", description="P&L analysis (sandbox-mode only today)")


@api.route("/symbols")
class PnlSymbolsV2(Resource):
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
                    "P&L symbol breakdown reads from the India sandbox; "
                    "ADR 0023 schedules provider-pluggable sandbox adapters."
                ),
                details={
                    "active_region": region,
                    "dimension": "sandbox_pnl",
                },
            ), 422

        try:
            from services.sandbox_service import (
                is_sandbox_mode,
                sandbox_get_pnl_symbols,
            )
        except ImportError as e:
            logger.exception("sandbox_service import failed: %s", e)
            return error("provider_error", "sandbox_service unavailable"), 502

        if not is_sandbox_mode():
            return error(
                "sandbox_disabled",
                "this endpoint is only available in sandbox/analyzer mode",
            ), 400

        body = request.get_json(silent=True) or {}
        try:
            success, payload, status = sandbox_get_pnl_symbols(
                body.get("apikey"), body,
            )
        except Exception as e:
            logger.exception("sandbox_get_pnl_symbols failed: %s", e)
            return error("provider_error", str(e)), 502

        if not success:
            return error(
                payload.get("code") or "provider_error",
                payload.get("message") or "P&L symbol breakdown failed",
                details=payload,
            ), status or 502

        return ok({"region_code": "india", "pnl_symbols": payload}), 200
