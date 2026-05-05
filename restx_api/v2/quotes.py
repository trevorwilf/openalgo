"""POST /api/v2/quotes — promoted-lane dispatch with fail-closed semantics.

Promoted path (``API_V2_<BROKER>=1`` + registered quote adapter):
dispatches each instrument through
:class:`~domain.broker_market_data.BrokerQuoteAdapter`. The legacy
``services.quotes_service`` is never loaded on this path.

Fail-closed semantics (Phase 2 v3, ADR 0018):

* Per-broker flag ON, no adapter, broker is non-India non-crypto →
  HTTP 503 ``promoted_capability_unavailable`` /
  ``quote_adapter_not_registered``. No legacy fallback.
* Per-broker flag ON, no adapter, broker is India or crypto →
  legacy fallback (preserves parity).
* Per-broker flag ON, adapter registered, instrument resolves →
  normalized quote.
* Per-broker flag ON, adapter registered, instrument fails to
  resolve → HTTP 422 ``instrument_not_resolvable`` (no legacy
  token DB lookup).
* Per-broker flag OFF, broker is India / crypto → legacy fallback
  (parity).
* Per-broker flag OFF, broker is non-India non-crypto → HTTP 503
  ``promoted_lane_required_for_non_india_broker`` (mirrors orders).
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
from utils.logging_context import log_context
from utils.metrics import counter

logger = get_logger(__name__)


def _broker_lane_check(broker: str, *, route: str) -> tuple[Any | None, int | None]:
    """Mirror of ``restx_api.v2.orders._broker_lane_check`` for the
    market-data routes. Returns ``(error_payload, status)`` to
    short-circuit when a non-India non-crypto broker tries to use
    the legacy fallback.
    """
    from utils.plugin_loader import get_broker_capabilities

    caps = get_broker_capabilities(broker) if broker else None
    if caps is None:
        return None, None
    regions = {str(r).strip().lower() for r in (caps.supported_regions or [])}
    is_india = "india" in regions or not regions
    broker_type = (getattr(caps, "broker_type", "") or "").strip().lower()
    is_crypto = broker_type == "crypto"
    if is_india or is_crypto:
        return None, None
    counter(
        "promoted_failclosed_total",
        {
            "broker": broker or "unknown",
            "code": "promoted_lane_required_for_non_india_broker",
            "route": route,
        },
    )
    return error(
        "promoted_lane_required_for_non_india_broker",
        f"broker {broker!r} cannot use the legacy lane (supported_regions "
        f"excludes 'india'). Set API_V2_{(broker or '').upper()}=1 and "
        "register a BrokerQuoteAdapter for this broker.",
        details={
            "broker_code": broker,
            "supported_regions": sorted(regions),
            "broker_type": broker_type,
        },
    ), 503


def _adapter_required_for_promoted_broker(broker: str) -> tuple[Any | None, int | None]:
    """When the per-broker flag is ON, the broker must have an adapter
    registered. India/crypto brokers may keep the legacy fallback for
    parity; non-India non-crypto brokers must have an adapter.
    """
    from utils.plugin_loader import get_broker_capabilities

    caps = get_broker_capabilities(broker) if broker else None
    if caps is None:
        # Unknown broker — fall through to the legacy fallback so the
        # existing error envelope renders.
        return None, None
    regions = {str(r).strip().lower() for r in (caps.supported_regions or [])}
    is_india = "india" in regions or not regions
    broker_type = (getattr(caps, "broker_type", "") or "").strip().lower()
    is_crypto = broker_type == "crypto"
    if is_india or is_crypto:
        return None, None
    counter(
        "broker_adapter_missing_total",
        {
            "broker": broker or "unknown",
            "region": next(iter(sorted(regions))) if regions else "unknown",
            "route": "/api/v2/quotes",
            "adapter_kind": "quote",
        },
    )
    counter(
        "promoted_failclosed_total",
        {
            "broker": broker or "unknown",
            "code": "quote_adapter_not_registered",
            "route": "/api/v2/quotes",
        },
    )
    return error(
        "promoted_capability_unavailable",
        f"broker {broker!r} is promoted but has no BrokerQuoteAdapter "
        "registered. Register a quote adapter via "
        "services.broker_market_data_registry.register_broker_quote_adapter.",
        details={
            "broker_code": broker,
            "sub_code": "quote_adapter_not_registered",
            "supported_regions": sorted(regions),
            "broker_type": broker_type,
        },
    ), 503


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
        flag_on = is_enabled(f"API_V2_{broker_upper}")
        promoted = get_broker_quote_adapter(broker) if flag_on else None
        if promoted is not None:
            with log_context(broker_code=broker, legacy_fallback=False):
                return _dispatch_promoted(
                    refs, broker=broker, auth_token=auth_token, adapter=promoted
                )
        # Flag ON but no adapter — non-India non-crypto brokers fail closed.
        if flag_on:
            adapter_err, adapter_status = _adapter_required_for_promoted_broker(broker)
            if adapter_err is not None:
                return adapter_err, adapter_status
            counter("promoted_legacy_fallback_total", {"broker": broker or "unknown"})
        # Flag OFF — non-India non-crypto brokers fail closed too.
        else:
            lane_err, lane_status = _broker_lane_check(broker, route="/api/v2/quotes")
            if lane_err is not None:
                return lane_err, lane_status
        with log_context(broker_code=broker, legacy_fallback=True):
            return _dispatch_legacy(refs, broker=broker, auth_token=auth_token)


def _dispatch_promoted(refs: list, *, broker: str, auth_token: str, adapter):
    """Promoted dispatch — never touches quotes_service or get_token."""
    from domain.errors import UnsupportedCapability
    from services.instrument_resolution import resolve_instrument
    from pydantic import ValidationError as PydValidationError

    from services.account_context_service import resolve_account_context
    from utils.plugin_loader import get_broker_capabilities

    capabilities = get_broker_capabilities(broker)
    account_ctx = resolve_account_context(
        broker_code=broker,
        auth_token=auth_token,
        capabilities=capabilities,
    )
    out: list[dict[str, Any]] = []
    region_label = (
        next(iter(sorted({str(r).strip().lower() for r in (capabilities.supported_regions or [])})), "unknown")
        if capabilities is not None and capabilities.supported_regions
        else "unknown"
    )
    for raw in refs:
        try:
            ref = _coerce_to_ref(raw)
        except (PydValidationError, ValueError) as e:
            counter(
                "instrument_resolution_failed_total",
                {
                    "broker": broker or "unknown",
                    "region": region_label,
                    "ref_kind": "invalid",
                    "identifier_type": "n/a",
                },
            )
            out.append({
                "instrument": raw,
                "error": {"code": "instrument_not_resolvable", "message": str(e)},
            })
            continue

        resolved = resolve_instrument(ref, broker_code=broker)
        if resolved is None:
            counter(
                "instrument_resolution_failed_total",
                {
                    "broker": broker or "unknown",
                    "region": region_label,
                    "ref_kind": getattr(ref, "kind", "unknown"),
                    "identifier_type": getattr(ref, "identifier_type", None) or "n/a",
                },
            )
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
            counter(
                "unsupported_capability_total",
                {
                    "broker": broker or "unknown",
                    "region": region_label,
                    "venue": resolved.venue_code or "unknown",
                    "asset_class": getattr(resolved, "asset_class", None) or "unknown",
                    "capability_name": getattr(e, "capability_name", "unknown"),
                },
            )
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
    from decimal import Decimal

    d = asdict(q)
    d["instrument_id"] = str(d.get("instrument_id")) if d.get("instrument_id") else None
    for k in ("bid", "ask", "last", "bid_size", "ask_size"):
        if d.get(k) is not None:
            d[k] = str(d[k])
    if d.get("timestamp") is not None and hasattr(q.timestamp, "isoformat"):
        d["timestamp"] = q.timestamp.astimezone(timezone.utc).isoformat()
    # Metadata may contain Decimal values (e.g. Alpaca's snapshot
    # endpoint surfaces OHLC as Decimal). Flask's default JSON
    # encoder doesn't handle Decimal, so the response would 500.
    # Stringify any Decimal values defensively.
    meta = d.get("metadata") or {}
    if isinstance(meta, dict):
        d["metadata"] = {
            mk: (str(mv) if isinstance(mv, Decimal) else mv)
            for mk, mv in meta.items()
        }
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
    with prior behavior. Only reachable when the broker is India/crypto
    OR the per-broker promoted flag is off and the broker is India/crypto.
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
