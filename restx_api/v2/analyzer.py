"""GET /api/v2/analyzer — region-gated analyzer/sandbox status.

Per ADR 0004 the analyzer (paper-trading sandbox with virtual capital)
stays India-limited; v2 callers from other regions get a structured
422 with the ``analyzer_india_region_only`` error code. India callers
fall through to the existing services.analyzer_service status read.
"""
from __future__ import annotations

from flask_restx import Namespace, Resource

from domain.errors import ErrorCode
from restx_api.v2._auth import error, ok, resolve_auth
from services.feature_gate_service import (
    active_region_code,
    is_india_region_active,
)
from utils.logging import get_logger

logger = get_logger(__name__)

api = Namespace("analyzer",
                description="Analyzer / sandbox mode status (India only)")


@api.route("")
@api.route("/")
class AnalyzerStatusV2(Resource):
    def get(self):
        auth_token, broker, auth_err = resolve_auth()
        if auth_err is not None:
            return error("unauthorized", auth_err), 401

        if not is_india_region_active():
            try:
                region = active_region_code()
            except Exception:
                region = "unknown"
            return error(
                ErrorCode.ANALYZER_INDIA_REGION_ONLY,
                (
                    "the analyzer / sandbox is India-only per ADR 0004; "
                    f"active region {region!r} is not supported."
                ),
                details={"active_region": region},
            ), 422

        try:
            from services.analyzer_service import get_analyzer_status
        except ImportError as e:
            logger.exception("analyzer_service import failed: %s", e)
            return error("provider_error", "analyzer_service unavailable"), 502

        try:
            success, payload, status = get_analyzer_status()
        except Exception as e:
            logger.exception("get_analyzer_status failed: %s", e)
            return error("provider_error", str(e)), 502

        if not success:
            return error(
                payload.get("code") or "provider_error",
                payload.get("message") or "analyzer status read failed",
                details=payload,
            ), status or 502

        return ok({"region_code": "india", "analyzer": payload}), 200
