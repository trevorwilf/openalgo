"""GET /api/v2/holdings — promoted-lane holdings.

Documented Phase 8-bis migration target. Translator hook:
``list_holdings_via_token(auth_token)``.

For brokers that distinguish intraday positions (MIS) from delivery
holdings (CNC) — primarily Indian brokers — the translator returns the
delivery-only set. For brokers that don't make this distinction
(Alpaca, most US/global brokers), the translator returns the same rows
as positions (no separate "delivery" concept exists).

Same auth + fail-closed pattern as ``/api/v2/orders``.
"""
from __future__ import annotations

from typing import Any

from flask_restx import Namespace, Resource

from restx_api.v2._auth import error, ok, resolve_auth
from services.broker_translator_registry import get_broker_translator
from utils.feature_flags import is_enabled
from utils.logging import get_logger

logger = get_logger(__name__)

api = Namespace("holdings", description="Normalized delivery holdings")


def _ensure_promoted(broker: str | None):
    if not broker:
        return None, error("bad_request", "broker not resolved from session"), 400
    flag_on = is_enabled(f"API_V2_{broker.upper()}")
    if not flag_on:
        return None, error(
            "promoted_lane_required",
            f"holdings on /api/v2 requires API_V2_{broker.upper()}=1",
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
class Holdings(Resource):
    def get(self):
        auth_token, broker, auth_err = resolve_auth()
        if auth_err is not None:
            return error("unauthorized", auth_err), 401

        promoted, err_payload, err_status = _ensure_promoted(broker)
        if promoted is None:
            return err_payload, err_status

        fn = getattr(promoted, "list_holdings_via_token", None)
        if not callable(fn):
            return error(
                "unimplemented",
                f"broker {broker!r} translator does not implement list_holdings_via_token",
                details={"broker_code": broker},
            ), 501

        try:
            rows = fn(auth_token)
        except RuntimeError as e:
            return error("broker_error", str(e)), 502
        except Exception as e:  # noqa: BLE001
            logger.exception("list_holdings failed for %s: %s", broker, e)
            return error("broker_error", str(e)), 502

        return ok({"holdings": rows, "count": len(rows)}), 200
