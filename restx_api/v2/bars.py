"""POST /api/v2/bars — promoted-lane dispatch with fail-closed semantics.

Mirror of :mod:`restx_api.v2.quotes`. Phase 2 v3 fail-closed
contract: a non-India non-crypto broker without a registered
``BrokerBarAdapter`` returns HTTP 503
``promoted_capability_unavailable`` / ``bar_adapter_not_registered``
instead of falling back to ``services.history_service``.
"""

from __future__ import annotations

from dataclasses import asdict
from datetime import datetime
from typing import Any

from flask import request
from flask_restx import Namespace, Resource

from restx_api.v2._auth import error, ok, resolve_auth
from services.broker_market_data_registry import get_broker_bar_adapter
from utils.feature_flags import is_enabled
from utils.logging import get_logger
from utils.logging_context import log_context
from utils.metrics import counter

logger = get_logger(__name__)


def _broker_lane_check(broker: str, *, route: str) -> tuple[Any | None, int | None]:
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
        "register a BrokerBarAdapter for this broker.",
        details={
            "broker_code": broker,
            "supported_regions": sorted(regions),
            "broker_type": broker_type,
        },
    ), 503


def _adapter_required_for_promoted_broker(broker: str) -> tuple[Any | None, int | None]:
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
        "broker_adapter_missing_total",
        {
            "broker": broker or "unknown",
            "region": next(iter(sorted(regions))) if regions else "unknown",
            "route": "/api/v2/bars",
            "adapter_kind": "bar",
        },
    )
    counter(
        "promoted_failclosed_total",
        {
            "broker": broker or "unknown",
            "code": "bar_adapter_not_registered",
            "route": "/api/v2/bars",
        },
    )
    return error(
        "promoted_capability_unavailable",
        f"broker {broker!r} is promoted but has no BrokerBarAdapter "
        "registered. Register a bar adapter via "
        "services.broker_market_data_registry.register_broker_bar_adapter.",
        details={
            "broker_code": broker,
            "sub_code": "bar_adapter_not_registered",
            "supported_regions": sorted(regions),
            "broker_type": broker_type,
        },
    ), 503


api = Namespace("bars", description="Normalized OHLCV history")


@api.route("")
@api.route("/")
class Bars(Resource):
    def post(self):
        auth_token, broker, auth_err = resolve_auth()
        if auth_err is not None:
            return error("unauthorized", auth_err), 401

        body = request.get_json(silent=True) or {}
        ref = body.get("instrument")
        interval = body.get("interval")
        start = body.get("start")
        end = body.get("end")
        if not (ref and interval and start and end):
            return error(
                "bad_request",
                "body must include `instrument`, `interval`, `start`, `end`",
            ), 400

        broker_upper = (broker or "").upper()
        flag_on = is_enabled(f"API_V2_{broker_upper}")
        promoted = get_broker_bar_adapter(broker) if flag_on else None
        if promoted is not None:
            with log_context(broker_code=broker, legacy_fallback=False):
                return _dispatch_promoted(
                    ref, interval=interval, start=start, end=end,
                    broker=broker, auth_token=auth_token, adapter=promoted,
                )
        if flag_on:
            adapter_err, adapter_status = _adapter_required_for_promoted_broker(broker)
            if adapter_err is not None:
                return adapter_err, adapter_status
            counter("promoted_legacy_fallback_total", {"broker": broker or "unknown"})
        else:
            lane_err, lane_status = _broker_lane_check(broker, route="/api/v2/bars")
            if lane_err is not None:
                return lane_err, lane_status
        with log_context(broker_code=broker, legacy_fallback=True):
            return _dispatch_legacy(
                ref, interval=interval, start=start, end=end,
                broker=broker, auth_token=auth_token,
            )


def _dispatch_promoted(
    raw_ref: Any, *, interval: str, start: Any, end: Any,
    broker: str, auth_token: str, adapter,
):
    from domain.broker_market_data import NormalizedBarRequest
    from domain.errors import UnsupportedCapability
    from restx_api.v2.quotes import _coerce_to_ref
    from services.instrument_resolution import resolve_instrument
    from pydantic import ValidationError as PydValidationError

    from services.account_context_service import resolve_account_context
    from utils.plugin_loader import get_broker_capabilities

    capabilities = get_broker_capabilities(broker)
    region_label = (
        next(iter(sorted({str(r).strip().lower() for r in (capabilities.supported_regions or [])})), "unknown")
        if capabilities is not None and capabilities.supported_regions
        else "unknown"
    )

    try:
        ref = _coerce_to_ref(raw_ref)
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
        return error("bad_request", f"invalid instrument ref: {e}"), 400

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
        return error(
            "instrument_not_resolvable",
            "ref not found in instrument universe",
        ), 422

    try:
        start_dt = _parse_dt(start)
        end_dt = _parse_dt(end)
    except ValueError as e:
        return error("bad_request", f"bad datetime: {e}"), 400

    req = NormalizedBarRequest(interval=interval, start=start_dt, end=end_dt)
    account_ctx = resolve_account_context(
        broker_code=broker,
        auth_token=auth_token,
        capabilities=capabilities,
    )

    try:
        bars = adapter.get_bars(resolved, req, account_ctx)
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
        return error("unsupported_capability", str(e), details={
            "broker_code": e.broker_code,
            "capability_name": e.capability_name,
        }), 422

    return ok({
        "instrument": {
            "instrument_id": str(resolved.instrument_id),
            "venue_code": resolved.venue_code,
            "canonical_symbol": resolved.canonical_symbol,
        },
        "interval": interval,
        "bars": [_bar_to_dict(b) for b in bars],
    }), 200


def _bar_to_dict(b) -> dict[str, Any]:
    d = asdict(b)
    for k in ("open", "high", "low", "close", "volume"):
        if d.get(k) is not None:
            d[k] = str(d[k])
    if hasattr(b.ts, "isoformat"):
        d["ts"] = b.ts.isoformat()
    return d


def _parse_dt(val: Any) -> datetime:
    if isinstance(val, datetime):
        return val
    if isinstance(val, str):
        s = val.replace("Z", "+00:00")
        return datetime.fromisoformat(s)
    raise ValueError(f"expected ISO-8601 string or datetime, got {type(val).__name__}")


def _dispatch_legacy(
    ref: Any, *, interval: str, start: Any, end: Any,
    broker: str, auth_token: str,
):
    from restx_api.v2.quotes import _resolve_ref
    from services.history_service import get_history_with_auth

    resolved = _resolve_ref(ref, broker_code=broker)
    if resolved is None:
        return error(
            "instrument_not_resolvable",
            "instrument ref could not be resolved",
        ), 400

    ok_flag, resp, status = get_history_with_auth(
        auth_token=auth_token,
        feed_token=None,
        broker=broker,
        symbol=resolved["canonical_symbol"],
        exchange=resolved["venue_code"],
        interval=interval,
        start_date=start,
        end_date=end,
    )
    if not ok_flag:
        return error("broker_error", resp.get("message", "history fetch failed")), status

    rows = resp.get("data", [])
    return ok({
        "instrument": {
            "instrument_id": resolved.get("instrument_id"),
            "venue_code": resolved["venue_code"],
            "canonical_symbol": resolved["canonical_symbol"],
        },
        "interval": interval,
        "bars": rows,
    }), 200
