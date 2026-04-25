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

Phase 3 fail-closed semantics (ADR 0008): when the per-broker flag is
set but the translator is missing, the route returns ``503
translator_not_registered`` instead of falling back to the legacy
translator. When the flag is *off* but the broker plugin's
``supported_regions`` excludes ``india`` and ``broker_type`` is not
``crypto``, the route returns ``503
promoted_lane_required_for_non_india_broker``. The intent is that a
non-India broker can never accidentally run through
``normalized_order_to_legacy_fields``.
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


def _broker_lane_check(broker: str) -> tuple[Any | None, int | None]:
    """Decide whether the current broker may use the legacy fallback.

    Phase 3 (ADR 0008): a broker whose plugin declares
    ``supported_regions`` that excludes ``india`` AND whose
    ``broker_type`` is not ``crypto`` may not silently fall back to the
    legacy Indian translator. Returns ``(error_payload, status)`` to
    short-circuit the request when the lane check fails. Returns
    ``(None, None)`` when the legacy fallback is allowed.
    """
    from utils.plugin_loader import get_broker_capabilities

    caps = get_broker_capabilities(broker) if broker else None
    if caps is None:
        # Unknown broker — let the existing legacy code path produce the
        # original (and expected) error envelope.
        return None, None
    regions = {str(r).strip().lower() for r in (caps.supported_regions or [])}
    is_india = "india" in regions or not regions  # legacy plugins → []
    broker_type = (getattr(caps, "broker_type", "") or "").strip().lower()
    is_crypto = broker_type == "crypto"
    if is_india or is_crypto:
        return None, None
    counter(
        "promoted_failclosed_total",
        {
            "broker": broker or "unknown",
            "code": "promoted_lane_required_for_non_india_broker",
        },
    )
    return error(
        "promoted_lane_required_for_non_india_broker",
        f"broker {broker!r} cannot use the legacy lane (supported_regions "
        f"excludes 'india'). Set API_V2_{(broker or '').upper()}=1 and "
        "register a BrokerOrderTranslator for this broker.",
        details={
            "broker_code": broker,
            "supported_regions": sorted(regions),
            "broker_type": broker_type,
        },
    ), 503

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
        # translator must be registered; otherwise the route falls
        # through to the legacy lane *for India and crypto brokers
        # only* (Phase 3 ADR 0008 fail-closed).
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

        # Legacy lane. First fail closed for non-India non-crypto
        # brokers — they must run through the promoted lane or not at
        # all (ADR 0008).
        lane_err, lane_status = _broker_lane_check(broker)
        if lane_err is not None:
            return lane_err, lane_status

        # Only count the legacy fallback when the flag was set — that is
        # the surprising case we want operators to alert on. Flag-off
        # is the baseline and must stay flat.
        if flag_on:
            counter("promoted_legacy_fallback_total", {"broker": broker or "unknown"})
        with log_context(broker_code=broker, legacy_fallback=True):
            return _dispatch_legacy(
                normalized, broker=broker, auth_token=auth_token, body=body
            )


def _capability_precheck(normalized, capabilities) -> Any | None:
    """Reject the order with ``unsupported_capability`` when the broker's
    declared capabilities do not include a requested primitive.

    Returns the error envelope or ``None`` if the order passes.
    """
    checks = (
        ("order_type", normalized.order_type, capabilities.supported_order_types),
        ("time_in_force", normalized.time_in_force, capabilities.supported_time_in_force),
        ("session", normalized.session, capabilities.supported_sessions),
        ("quantity_unit", normalized.quantity_unit, capabilities.supported_quantity_units),
    )
    for field_name, value, supported in checks:
        if supported and value not in supported:
            counter(
                "promoted_failclosed_total",
                {"broker": capabilities.broker_code, "code": "unsupported_capability"},
            )
            return error(
                "unsupported_capability",
                f"broker {capabilities.broker_code!r} does not support "
                f"{field_name}={getattr(value, 'value', value)!s}",
                details={
                    "broker_code": capabilities.broker_code,
                    "capability_name": field_name,
                    "requested": getattr(value, "value", str(value)),
                    "supported": [getattr(s, "value", str(s)) for s in supported],
                },
            )
    return None


def _dispatch_promoted(normalized, *, broker: str, auth_token: str, promoted):
    """Promoted-lane dispatch. Does not touch the legacy translator."""
    from datetime import datetime, timezone

    from domain.errors import UnsupportedCapability
    from services.account_context_service import resolve_account_context
    from services.instrument_resolution import resolve_instrument
    from services.rule_enforcement import OrderRuleViolation, check_order
    from utils.plugin_loader import get_broker_capabilities

    resolved = resolve_instrument(normalized.instrument, broker_code=broker)
    if resolved is None and normalized.instrument.kind != "venue_symbol":
        # venue_symbol is lenient — a broker adapter may still recognize a
        # symbol that isn't in the canonical universe yet (Phase 6 sync).
        return error(
            "instrument_not_resolvable",
            "instrument ref not found in instrument universe",
        ), 404

    capabilities = get_broker_capabilities(broker)
    account_ctx = resolve_account_context(
        broker_code=broker,
        auth_token=auth_token,
        capabilities=capabilities,
    )

    # Capability completeness gate — fail before the wire if the
    # promoted broker capabilities table doesn't list the requested
    # primitive. Phase 3 ADR 0008 calls for a structured 422.
    if capabilities is not None:
        cap_err = _capability_precheck(normalized, capabilities)
        if cap_err is not None:
            return cap_err, 422

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
            account_ctx=account_ctx,
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
