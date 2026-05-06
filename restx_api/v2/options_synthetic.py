"""GET /api/v2/options/synthetic-future — region-gated synthetic future.

The synthetic-future calculation derives an implied futures price from
a (call - put) pair on the same strike+expiry. It's currently India-
shaped (lot size, currency, NFO/BFO venue assumptions in the legacy
service); ADR 0020 keeps it gated behind ``is_india_region_active()``
and ADR 0023 schedules a provider-pluggable rewrite.

The v2 endpoint exists so the route is reachable (no SPA-shell fall-
through) and so non-India callers get a structured 422 with the
stable ``synthetic_future_disabled_in_region`` error code instead of
HTML. India callers fall through to the legacy v1 service.
"""
from __future__ import annotations

from datetime import date as _date
from decimal import Decimal, InvalidOperation

from flask import request
from flask_restx import Namespace, Resource

from domain.errors import ErrorCode
from restx_api.v2._auth import (
    error,
    ok,
    resolve_active_region_from_broker,
    resolve_auth,
)
from utils.logging import get_logger

logger = get_logger(__name__)

api = Namespace(
    "options_synthetic_future",
    description="Synthetic-future from same-strike call/put pair",
)


@api.route("")
@api.route("/")
class OptionsSyntheticFuture(Resource):
    def get(self):
        auth_token, broker, auth_err = resolve_auth()
        if auth_err is not None:
            return error("unauthorized", auth_err), 401

        region = resolve_active_region_from_broker(broker)
        if region != "india":
            return error(
                ErrorCode.SYNTHETIC_FUTURE_DISABLED_IN_REGION,
                (
                    "synthetic-future calculation is currently India-only "
                    f"(active region {region!r}); ADR 0023 schedules the "
                    "provider-pluggable rewrite."
                ),
                details={"active_region": region, "broker_code": broker},
            ), 422

        underlying = (request.args.get("underlying") or "").strip().upper()
        expiry_str = request.args.get("expiry")
        strike_str = request.args.get("strike")
        for label, val in [("underlying", underlying),
                            ("expiry", expiry_str),
                            ("strike", strike_str)]:
            if not val:
                return error("bad_request",
                             f"{label} query param required"), 400
        try:
            expiry = _date.fromisoformat(expiry_str)
            strike = Decimal(strike_str)
        except (ValueError, InvalidOperation) as e:
            return error("bad_request", f"could not parse params: {e}"), 400

        try:
            from services.synthetic_future_service import (
                get_synthetic_future,
            )
        except ImportError as e:
            logger.exception("synthetic_future_service import failed: %s", e)
            return error("provider_error", "synthetic_future_service unavailable"), 502

        try:
            success, payload, status = get_synthetic_future(
                symbol=underlying,
                expiry=expiry.strftime("%d-%b-%Y").upper(),
                strike=str(strike),
                api_key=request.args.get("apikey"),
            )
        except Exception as e:
            logger.exception("synthetic_future call failed: %s", e)
            return error("provider_error", str(e)), 502

        if not success:
            return error(
                payload.get("code") or "provider_error",
                payload.get("message") or "synthetic-future calculation failed",
                details=payload,
            ), status or 502

        return ok({
            "underlying": underlying,
            "expiry": expiry.isoformat(),
            "strike": str(strike),
            "region_code": "india",
            "synthetic_future": payload,
        }), 200
