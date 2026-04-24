"""POST /api/v2/quotes — promoted-lane dispatch with legacy fallback.

Promoted path (``API_V2_<BROKER>=1`` + registered quote adapter):
dispatches each instrument through
:class:`~domain.broker_market_data.BrokerQuoteAdapter`. The legacy
``services.quotes_service`` is never loaded on this path.

Legacy path (default): reuses the pre-existing flow, which is the
bit-identical v1 behavior.
"""

from __future__ import annotations

from dataclasses import asdict
from datetime import datetime, timezone
from typing import Any

from flask import request
from flask_restx import Namespace, Resource

from restx_api.v2._auth import error, ok, resolve_auth
from services.broker_market_data_registry import get_broker_quote_adapter
from utils.feature_flags import is_enabled
from utils.logging import get_logger

logger = get_logger(__name__)

api = Namespace("quotes", description="Normalized quote fetch")


@api.route("")
@api.route("/")
class Quotes(Resource):
    def post(self):
        auth_token, broker, auth_err = resolve_auth()
        if auth_err is not None:
            return error("unauthorized", auth_err), 401

        body = request.get_json(silent=True) or {}
        refs = body.get("instruments")
        if not isinstance(refs, list) or not refs:
            return error(
                "bad_request", "body.instruments[] is required and must be non-empty"
            ), 400

        broker_upper = (broker or "").upper()
        promoted = (
            get_broker_quote_adapter(broker)
            if is_enabled(f"API_V2_{broker_upper}")
            else None
        )
        if promoted is not None:
            return _dispatch_promoted(
                refs, broker=broker, auth_token=auth_token, adapter=promoted
            )
        return _dispatch_legacy(refs, broker=broker, auth_token=auth_token)


def _dispatch_promoted(refs: list, *, broker: str, auth_token: str, adapter):
    """Promoted dispatch — never touches quotes_service or get_token."""
    from domain.errors import UnsupportedCapability
    from domain.instrument_ref import InstrumentRef
    from services.instrument_resolution import resolve_instrument
    from pydantic import ValidationError as PydValidationError

    account_ctx: dict[str, Any] = {"broker_code": broker, "auth_token": auth_token}
    out: list[dict[str, Any]] = []
    for raw in refs:
        try:
            ref = _coerce_to_ref(raw)
        except (PydValidationError, ValueError) as e:
            out.append({
                "instrument": raw,
                "error": {"code": "instrument_not_resolvable", "message": str(e)},
            })
            continue

        resolved = resolve_instrument(ref, broker_code=broker)
        if resolved is None:
            out.append({
                "instrument": raw,
                "error": {
                    "code": "instrument_not_resolvable",
                    "message": "ref not found in instrument universe",
                },
            })
            continue

        try:
            quote = adapter.get_quote(resolved, account_ctx)
        except UnsupportedCapability as e:
            out.append({
                "instrument": {
                    "instrument_id": str(resolved.instrument_id),
                    "venue_code": resolved.venue_code,
                    "canonical_symbol": resolved.canonical_symbol,
                },
                "error": {
                    "code": "unsupported_capability",
                    "message": str(e),
                },
            })
            continue

        out.append({
            "instrument": {
                "instrument_id": str(resolved.instrument_id),
                "venue_code": resolved.venue_code,
                "canonical_symbol": resolved.canonical_symbol,
            },
            "timestamp": (
                quote.timestamp.astimezone(timezone.utc).isoformat()
                if quote.timestamp is not None
                else datetime.now(timezone.utc).isoformat()
            ),
            "quote": _quote_dict(quote),
        })
    return ok(out), 200


def _quote_dict(q) -> dict[str, Any]:
    d = asdict(q)
    d["instrument_id"] = str(d.get("instrument_id")) if d.get("instrument_id") else None
    for k in ("bid", "ask", "last", "bid_size", "ask_size"):
        if d.get(k) is not None:
            d[k] = str(d[k])
    if d.get("timestamp") is not None and hasattr(q.timestamp, "isoformat"):
        d["timestamp"] = q.timestamp.astimezone(timezone.utc).isoformat()
    return d


def _coerce_to_ref(raw: Any):
    from domain.instrument_ref import InstrumentRef

    if not isinstance(raw, dict):
        raise ValueError("instrument ref must be an object")
    # Accept the legacy {symbol, exchange} shape as venue_symbol.
    if raw.get("symbol") and raw.get("exchange") and not raw.get("canonical_symbol"):
        return InstrumentRef(
            venue_code=raw["exchange"], canonical_symbol=raw["symbol"]
        )
    # Filter to only the keys InstrumentRef accepts to keep
    # extra="forbid" happy.
    permitted = {
        "instrument_id", "venue_code", "canonical_symbol",
        "identifier_type", "identifier_value", "broker_code",
    }
    cleaned = {k: v for k, v in raw.items() if k in permitted}
    return InstrumentRef(**cleaned)


def _dispatch_legacy(refs: list, *, broker: str, auth_token: str):
    """Legacy dispatch — imports quotes_service locally. Bit-identical
    with prior behavior.
    """
    from services.quotes_service import get_quotes_with_auth

    out: list[dict[str, Any]] = []
    for raw_ref in refs:
        resolved = _resolve_ref(raw_ref, broker_code=broker)
        if resolved is None:
            out.append({
                "instrument": raw_ref,
                "error": {
                    "code": "instrument_not_resolvable",
                    "message": "ref could not be resolved",
                },
            })
            continue

        ok_flag, resp, status = get_quotes_with_auth(
            auth_token=auth_token,
            feed_token=None,
            broker=broker,
            symbol=resolved["canonical_symbol"],
            exchange=resolved["venue_code"],
        )
        if not ok_flag:
            out.append({
                "instrument": {
                    "instrument_id": resolved.get("instrument_id"),
                    "venue_code": resolved["venue_code"],
                    "canonical_symbol": resolved["canonical_symbol"],
                },
                "error": {
                    "code": "broker_error",
                    "message": resp.get("message", "quote fetch failed"),
                },
            })
            continue

        payload = resp.get("data", {})
        out.append({
            "instrument": {
                "instrument_id": resolved.get("instrument_id"),
                "venue_code": resolved["venue_code"],
                "canonical_symbol": resolved["canonical_symbol"],
            },
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "quote": payload,
        })
    return ok(out), 200


def _resolve_ref(raw: Any, broker_code: str | None) -> dict | None:
    """Legacy ref resolution for the legacy dispatcher.

    Accepts both normalized and legacy ``{symbol, exchange}`` shapes and
    returns a dict of venue_code + canonical_symbol for the legacy
    quotes_service. Still used by ``restx_api.v2.bars._dispatch_legacy``.
    """
    if not isinstance(raw, dict):
        return None
    if raw.get("venue_code") and raw.get("canonical_symbol"):
        return {
            "venue_code": raw["venue_code"],
            "canonical_symbol": raw["canonical_symbol"],
            "instrument_id": raw.get("instrument_id"),
        }
    if raw.get("symbol") and raw.get("exchange"):
        return {
            "venue_code": raw["exchange"],
            "canonical_symbol": raw["symbol"],
            "instrument_id": None,
        }
    if raw.get("instrument_id"):
        import uuid

        from database.instruments_repo import instruments_get_by_id

        try:
            uid = uuid.UUID(str(raw["instrument_id"]))
        except ValueError:
            return None
        inst = instruments_get_by_id(uid)
        if inst is None:
            return None
        return {
            "venue_code": inst.venue_code,
            "canonical_symbol": inst.canonical_symbol,
            "instrument_id": str(inst.instrument_id),
        }
    return None
