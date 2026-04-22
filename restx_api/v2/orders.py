"""POST /api/v2/orders — accept a NormalizedOrderRequest, dispatch via v1 service.

Translates the normalized request to the legacy Indian shape
(`domain.translators.normalized_order_to_legacy_fields`) and calls the
same ``services.place_order_service.place_order_with_auth`` that v1
uses. Broker modules are NOT touched. The translator raises
``UnsupportedCapability`` for concepts the legacy Indian API cannot
express; those surface as a structured 422 error.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Any

from flask import request
from flask_restx import Namespace, Resource

from restx_api.v2._auth import error, ok, resolve_auth
from utils.logging import get_logger

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

        # Parse into the normalized DTO.
        from domain.orders import NormalizedOrderRequest
        from pydantic import ValidationError as PydValidationError

        try:
            normalized = NormalizedOrderRequest(**order_body)
        except PydValidationError as e:
            # `e.errors()` can embed `ValueError` instances under `ctx`
            # which Flask's JSON encoder cannot serialize. Stringify
            # before returning.
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

        # Translate to legacy Indian wire format.
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

        # Build the legacy v1 place_order payload and dispatch.
        legacy_data: dict[str, Any] = {
            "apikey": (request.get_json(silent=True) or {}).get("apikey", ""),
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

        # Normalize the response envelope. Legacy fields preserved under
        # `legacy` for debugging.
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
