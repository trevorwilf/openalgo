"""POST /api/v2/orders — promoted-lane dispatch, with legacy fallback.

Promoted path (when ``API_V2_<BROKER_CODE_UPPER>=1`` is set and a
:class:`~domain.broker_translator.BrokerOrderTranslator` is registered
for the broker): the request body is validated, translated, and
dispatched through the per-broker native order API. The legacy
Indian translator is never loaded on this path.

Legacy path (default): the normalized request is translated back to
the Indian shape via
:func:`domain.translators.normalized_order_to_legacy_fields` and
dispatched through :func:`services.place_order_service.place_order_with_auth`,
matching ``/api/v1`` bit-identically.
"""

from __future__ import annotations

from typing import Any

from flask import request
from flask_restx import Namespace, Resource

from restx_api.v2._auth import error, ok, resolve_auth
from services.broker_translator_registry import get_broker_translator
from utils.feature_flags import is_enabled
from utils.logging import get_logger
from utils.logging_context import log_context
from utils.metrics import counter

logger = get_logger(__name__)

api = Namespace("orders", description="Normalized order placement")


@api.route("")
@api.route("/")
class Orders(Resource):
    def post(self):
        auth_token, broker, auth_err = resolve_auth()
        if auth_err is not None:
            return error("unauthorized", auth_err), 401

        body = request.get_json(silent=True) or {}

        # Strip fields that belong to the /api/v2 envelope, not to the
        # normalized order body itself. NormalizedOrderRequest has
        # extra="forbid", so any stray field triggers a validation error.
        order_body = {k: v for k, v in body.items() if k != "apikey"}

        from domain.orders import NormalizedOrderRequest
        from pydantic import ValidationError as PydValidationError

        try:
            normalized = NormalizedOrderRequest(**order_body)
        except PydValidationError as e:
            stringified = [
                {
                    "loc": [str(x) for x in err.get("loc", [])],
                    "msg": str(err.get("msg", "")),
                    "type": str(err.get("type", "")),
                }
                for err in e.errors()
            ]
            return error("validation_error", "body failed validation", details={
                "pydantic_errors": stringified,
            }), 422

        # Decide the lane. Per-broker promotion flag must be set AND a
        # translator must be registered; otherwise fall through to legacy.
        broker_upper = (broker or "").upper()
        flag_name = f"API_V2_{broker_upper}"
        flag_on = is_enabled(flag_name)
        promoted = get_broker_translator(broker) if flag_on else None

        if promoted is not None:
            with log_context(
                broker_code=broker,
                session=normalized.session.value,
                time_in_force=normalized.time_in_force.value,
                quantity_unit=normalized.quantity_unit.value,
                legacy_fallback=False,
            ):
                return _dispatch_promoted(
                    normalized, broker=broker, auth_token=auth_token, promoted=promoted
                )
        # Legacy fallback. Only count it if the flag was set — that is
        # the surprising case we want operators to alert on. Flag-off
        # is the baseline and must stay flat.
        if flag_on:
            counter("promoted_legacy_fallback_total", {"broker": broker or "unknown"})
        with log_context(broker_code=broker, legacy_fallback=True):
            return _dispatch_legacy(
                normalized, broker=broker, auth_token=auth_token, body=body
            )


def _dispatch_promoted(normalized, *, broker: str, auth_token: str, promoted):
    """Promoted-lane dispatch. Does not touch the legacy translator."""
    from datetime import datetime, timezone

    from domain.errors import UnsupportedCapability
    from services.instrument_resolution import resolve_instrument
    from services.rule_enforcement import OrderRuleViolation, check_order

    resolved = resolve_instrument(normalized.instrument, broker_code=broker)
    if resolved is None and normalized.instrument.kind != "venue_symbol":
        # venue_symbol is lenient — a broker adapter may still recognize a
        # symbol that isn't in the canonical universe yet (Phase 6 sync).
        return error(
            "instrument_not_resolvable",
            "instrument ref not found in instrument universe",
        ), 404

    account_ctx: dict[str, Any] = {
        "broker_code": broker,
        "account_id": auth_token,
    }

    try:
        check_order(
            normalized,
            broker_code=broker,
            venue_code=(
                resolved.venue_code
                if resolved is not None
                else normalized.instrument.venue_code
            ),
            asset_class=(resolved.asset_class if resolved is not None else None),
            now_tz_aware=datetime.now(timezone.utc),
            allows_fractional=(
                resolved.supports_fractional if resolved is not None else None
            ),
        )
    except OrderRuleViolation as e:
        return error(
            "rule_violation",
            e.message,
            details={"code": e.code, "rule_id": e.rule_id},
        ), 422

    try:
        promoted.validate(normalized, resolved, account_ctx)
    except UnsupportedCapability as e:
        return error("unsupported_capability", str(e), details={
            "broker_code": e.broker_code,
            "capability_name": e.capability_name,
        }), 422
    except ValueError as e:
        return error("validation_error", str(e)), 422

    instrument = resolved

    try:
        native_payload = promoted.to_native(normalized, instrument, account_ctx)
    except UnsupportedCapability as e:
        return error("unsupported_capability", str(e), details={
            "broker_code": e.broker_code,
            "capability_name": e.capability_name,
        }), 422

    # Promoted dispatcher delegates the actual wire call to the broker
    # adapter. Phase 6 wires a real HTTP send; for now, call a pluggable
    # hook the translator MAY provide under `send_native`. Tests
    # monkeypatch this hook to avoid the network.
    send = getattr(promoted, "send_native", None)
    if not callable(send):
        return error(
            "broker_adapter_missing",
            f"broker {broker!r} is promoted but has no send_native hook",
        ), 503

    try:
        native_resp = send(native_payload, account_ctx)
    except UnsupportedCapability as e:
        return error("unsupported_capability", str(e), details={
            "broker_code": e.broker_code,
            "capability_name": e.capability_name,
        }), 422
    except Exception as e:  # pragma: no cover - last-resort guard
        logger.exception("promoted broker send_native failed: %s", e)
        return error("broker_error", str(e)), 502

    try:
        normalized_resp = promoted.from_native_order_response(native_resp, instrument)
    except ValueError as e:
        return error("broker_error", f"malformed broker response: {e}"), 502

    ref = normalized.instrument
    ref_view = {
        "instrument_id": str(ref.instrument_id) if ref.instrument_id else None,
        "venue_code": ref.venue_code,
        "canonical_symbol": ref.canonical_symbol,
    }
    payload = {
        "instrument": ref_view,
        **normalized_resp,
    }
    return ok(payload), 200


def _dispatch_legacy(normalized, *, broker: str, auth_token: str, body: dict):
    """Legacy-lane dispatch — bit-identical with prior behavior.

    The legacy translator is imported here (not at module top) so the
    lane-isolation test can prove promoted requests never load it.
    """
    from domain.errors import UnsupportedCapability
    from domain.translators import normalized_order_to_legacy_fields

    try:
        legacy = normalized_order_to_legacy_fields(normalized)
    except UnsupportedCapability as e:
        return error("unsupported_capability", str(e), details={
            "broker_code": e.broker_code,
            "capability_name": e.capability_name,
        }), 422

    ref = normalized.instrument
    if ref.kind == "venue_symbol":
        symbol = ref.canonical_symbol
        exchange = ref.venue_code
    elif ref.kind == "id":
        from database.instruments_repo import instruments_get_by_id

        inst = instruments_get_by_id(ref.instrument_id)
        if inst is None:
            return error("instrument_not_resolvable",
                         f"instrument_id={ref.instrument_id} not found"), 404
        symbol = inst.canonical_symbol
        exchange = inst.venue_code
    else:
        return error("bad_request",
                     "v2 orders currently support id / venue_symbol refs only"), 400

    legacy_data: dict[str, Any] = {
        "apikey": body.get("apikey", ""),
        "strategy": normalized.strategy_tag or "api-v2",
        "symbol": symbol,
        "exchange": exchange,
        "action": legacy["side"],
        "quantity": str(normalized.quantity),
        "price_type": legacy["pricetype"],
        "product_type": legacy["product"],
    }
    if normalized.price is not None:
        legacy_data["price"] = str(normalized.price)
    if normalized.trigger_price is not None:
        legacy_data["trigger_price"] = str(normalized.trigger_price)
    if normalized.client_order_id:
        legacy_data["client_order_id"] = normalized.client_order_id

    from services.place_order_service import place_order_with_auth

    ok_flag, resp, status = place_order_with_auth(
        auth_token=auth_token, broker=broker, order_data=legacy_data,
    )
    if not ok_flag:
        return error("broker_error", resp.get("message", "place order failed"),
                     details=resp), status

    return ok({
        "order_id": resp.get("orderid") or resp.get("order_id"),
        "status": resp.get("order_status") or "submitted",
        "instrument": {
            "instrument_id": str(ref.instrument_id) if ref.instrument_id else None,
            "venue_code": exchange,
            "canonical_symbol": symbol,
        },
        "legacy": resp,
    }), status
