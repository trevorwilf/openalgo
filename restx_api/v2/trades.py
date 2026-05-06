"""GET /api/v2/trades — promoted-lane tradebook.

Documented Phase 8-bis migration target. Translator hook:
``list_trades_via_token(auth_token, *, date=None, page_size=100)``.

Alpaca implementation calls ``GET /v2/account/activities`` with
``activity_types=FILL`` and returns one row per per-execution fill —
mirroring Indian-broker tradebook semantics.

Same auth + fail-closed pattern as ``/api/v2/orders``: API key in body
or query, broker plugin must declare ``API_V2_<BROKER>=1`` and have a
registered translator.
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

api = Namespace("trades", description="Normalized tradebook (per-fill)")


def _ensure_promoted(broker: str | None):
    """Mirror of ``restx_api.v2.orders._ensure_promoted`` — same
    fail-closed contract."""
    if not broker:
        return None, error("bad_request", "broker not resolved from session"), 400
    flag_on = is_enabled(f"API_V2_{broker.upper()}")
    if not flag_on:
        return None, error(
            "promoted_lane_required",
            f"trades on /api/v2 requires API_V2_{broker.upper()}=1",
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
class Trades(Resource):
    def get(self):
        auth_token, broker, auth_err = resolve_auth()
        if auth_err is not None:
            return error("unauthorized", auth_err), 401

        promoted, err_payload, err_status = _ensure_promoted(broker)
        if promoted is None:
            return err_payload, err_status

        fn = getattr(promoted, "list_trades_via_token", None)
        if not callable(fn):
            return error(
                "unimplemented",
                f"broker {broker!r} translator does not implement list_trades_via_token",
                details={"broker_code": broker},
            ), 501

        date = request.args.get("date") or None
        try:
            page_size = int(request.args.get("page_size", "100"))
        except ValueError:
            return error("bad_request", "page_size must be an integer"), 400
        if page_size <= 0 or page_size > 500:
            return error("bad_request", "page_size must be 1..500"), 400

        try:
            rows = fn(auth_token, date=date, page_size=page_size)
        except RuntimeError as e:
            return error("broker_error", str(e)), 502
        except Exception as e:  # noqa: BLE001
            logger.exception("list_trades failed for %s: %s", broker, e)
            return error("broker_error", str(e)), 502

        return ok({"trades": rows, "count": len(rows)}), 200
