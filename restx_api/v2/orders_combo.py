"""POST /api/v2/orders/combo — promoted-lane combo order dispatch.

Phase 6 v3 (ADR 0022). Mirrors :mod:`restx_api.v2.orders` but takes a
:class:`NormalizedComboOrderRequest` instead of a single
:class:`NormalizedOrderRequest`. Translators opt in by exposing a
``to_native_combo`` method and listing the combo_type in their broker
capabilities' ``supports_combo_types``.

Same fail-closed contract as v2 orders: missing translator returns
HTTP 503 ``translator_not_registered``; non-India non-crypto broker
without an enabled flag returns HTTP 503
``promoted_lane_required_for_non_india_broker``; combo_type not
supported by translator returns HTTP 422 ``unsupported_capability``.
"""

from __future__ import annotations

from flask import request
from flask_restx import Namespace, Resource

from restx_api.v2._auth import error, ok, resolve_auth
from services.broker_translator_registry import get_broker_translator
from utils.feature_flags import is_enabled
from utils.logging import get_logger
from utils.logging_context import log_context
from utils.metrics import counter

logger = get_logger(__name__)

api = Namespace("orders_combo", description="Normalized combo / multi-leg orders")


@api.route("")
@api.route("/")
class OrdersCombo(Resource):
    def post(self):
        auth_token, broker, auth_err = resolve_auth()
        if auth_err is not None:
            return error("unauthorized", auth_err), 401

        body = request.get_json(silent=True) or {}
        combo_body = {k: v for k, v in body.items() if k != "apikey"}

        from domain.orders import NormalizedComboOrderRequest
        from pydantic import ValidationError as PydValidationError

        try:
            combo = NormalizedComboOrderRequest(**combo_body)
        except PydValidationError as e:
            return error("validation_error", "body failed validation", details={
                "pydantic_errors": [
                    {
                        "loc": [str(x) for x in err.get("loc", [])],
                        "msg": str(err.get("msg", "")),
                        "type": str(err.get("type", "")),
                    }
                    for err in e.errors()
                ],
            }), 422

        broker_upper = (broker or "").upper()
        flag_name = f"API_V2_{broker_upper}"
        flag_on = is_enabled(flag_name)
        promoted = get_broker_translator(broker) if flag_on else None
        if flag_on and promoted is None:
            counter(
                "promoted_failclosed_total",
                {"broker": broker or "unknown", "code": "translator_not_registered"},
            )
            return error(
                "translator_not_registered",
                f"Promoted lane is enabled for broker {broker!r} but no "
                "BrokerOrderTranslator is registered.",
                details={"broker_code": broker, "flag": flag_name},
            ), 503

        if promoted is None:
            counter(
                "promoted_failclosed_total",
                {"broker": broker or "unknown", "code": "promoted_lane_required_for_non_india_broker"},
            )
            return error(
                "promoted_lane_required_for_non_india_broker",
                f"combo orders require a promoted broker translator; "
                f"set API_V2_{broker_upper}=1 and register a translator.",
                details={"broker_code": broker, "flag": flag_name},
            ), 503

        if not hasattr(promoted, "to_native_combo"):
            counter(
                "unsupported_capability_total",
                {"broker": broker or "unknown", "capability_name": "combo"},
            )
            return error(
                "unsupported_capability",
                f"broker {broker!r} translator does not implement "
                "to_native_combo; combo orders not supported.",
                details={"broker_code": broker, "capability_name": "combo"},
            ), 422

        # Capability gate — declared combo_types.
        from utils.plugin_loader import get_broker_capabilities
        caps = get_broker_capabilities(broker)
        if caps is not None:
            supported = list(getattr(caps, "supports_combo_types", None) or [])
            if supported and combo.combo_type not in supported:
                counter(
                    "unsupported_capability_total",
                    {
                        "broker": broker or "unknown",
                        "capability_name": "combo_type",
                    },
                )
                return error(
                    "unsupported_capability",
                    f"broker {broker!r} does not support combo_type="
                    f"{combo.combo_type.value}",
                    details={
                        "broker_code": broker,
                        "capability_name": "combo_type",
                        "requested": combo.combo_type.value,
                        "supported": [
                            getattr(t, "value", str(t)) for t in supported
                        ],
                    },
                ), 422

        with log_context(
            broker_code=broker,
            combo_type=combo.combo_type.value,
            legs=len(combo.legs),
        ):
            return _dispatch_combo(combo, broker=broker, auth_token=auth_token, promoted=promoted)


def _dispatch_combo(combo, *, broker: str, auth_token: str, promoted):
    from domain.errors import UnsupportedCapability
    from services.account_context_service import resolve_account_context
    from services.instrument_resolution import resolve_instrument
    from utils.plugin_loader import get_broker_capabilities

    capabilities = get_broker_capabilities(broker)
    account_ctx = resolve_account_context(
        broker_code=broker,
        auth_token=auth_token,
        capabilities=capabilities,
    )

    instruments_by_leg = []
    for i, leg in enumerate(combo.legs):
        resolved = resolve_instrument(leg.instrument_ref, broker_code=broker)
        if resolved is None:
            return error(
                "instrument_not_resolvable",
                f"leg {i}: instrument ref not found in instrument universe",
                details={"leg_index": i},
            ), 422
        instruments_by_leg.append(resolved)

    try:
        native_payload = promoted.to_native_combo(
            combo, instruments_by_leg, account_ctx
        )
    except UnsupportedCapability as e:
        return error("unsupported_capability", str(e), details={
            "broker_code": e.broker_code,
            "capability_name": e.capability_name,
        }), 422

    send = getattr(promoted, "send_native", None)
    if not callable(send):
        return error(
            "broker_adapter_missing",
            f"broker {broker!r} translator has no send_native hook",
        ), 503

    try:
        native_resp = send(native_payload, account_ctx)
    except UnsupportedCapability as e:
        return error("unsupported_capability", str(e), details={
            "broker_code": e.broker_code,
            "capability_name": e.capability_name,
        }), 422
    except Exception as e:  # noqa: BLE001 — broker-side last-resort
        logger.exception(
            "combo broker send_native failed for %s: %s", broker, e
        )
        return error("broker_error", str(e)), 502

    return ok({
        "combo_type": combo.combo_type.value,
        "link_id": combo.link_id,
        "legs": [
            {
                "instrument_id": str(r.instrument_id),
                "venue_code": r.venue_code,
                "canonical_symbol": r.canonical_symbol,
            }
            for r in instruments_by_leg
        ],
        "native_response": native_resp,
    }), 200
