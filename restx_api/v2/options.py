"""GET /api/v2/options/{expiries,chain} — region-driven options surface.

ADR 0027 ships per-region ``OptionsProvider`` implementations
(``services.options.providers.*``). These v2 routes expose the
already-implemented provider methods (``list_expiries``,
``get_chain``) over HTTP under the canonical v2 envelope.

Region selection: routes resolve the active region via
``services.feature_gate_service.active_region_code`` (which reads the
session's broker plugin's ``supported_regions``). When the region
isn't registered with an options provider, the route returns
``503 options_provider_not_registered``.

Routes:
  GET /api/v2/options/expiries?underlying=AAPL&asof=YYYY-MM-DD
      → {"data": {"underlying": "AAPL", "region_code": "us",
                   "expiries": ["2026-05-08", "2026-05-15", ...]}}

  GET /api/v2/options/chain?underlying=AAPL&expiry=YYYY-MM-DD
      → {"data": {"underlying": "AAPL", "expiry": "2026-05-15",
                   "region_code": "us",
                   "calls": [{strike, lot_size, multiplier,
                              currency, venue_code, ...}, ...],
                   "puts":  [...]}}
"""
from __future__ import annotations

from datetime import date as _date
from decimal import Decimal
from typing import Any

from flask import request
from flask_restx import Namespace, Resource

from restx_api.v2._auth import error, ok, resolve_auth
from utils.logging import get_logger

logger = get_logger(__name__)

api_expiries = Namespace("options_expiries",
                          description="Options expiry list per underlying")
api_chain = Namespace("options_chain",
                       description="Options chain (calls + puts) per (underlying, expiry)")


def _resolve_options_provider(broker: str | None):
    """Return ``(provider, error_payload, http_status)``.

    Resolves the active region from the broker's plugin capabilities
    (Indian broker → "india"; alpaca → "us"; etc.) and looks up the
    matching options provider. Returns a structured 503 when no
    provider is registered for the region.
    """
    from services.feature_gate_service import active_region_code
    from services.options.dispatcher import get_options_provider_or_none

    try:
        region = active_region_code()
    except Exception as e:
        logger.exception("could not resolve active region: %s", e)
        return None, error(
            "missing_region_context",
            f"could not resolve region for broker {broker!r}: {e}",
        ), 503

    provider = get_options_provider_or_none(region)
    if provider is None:
        return None, error(
            "options_provider_not_registered",
            f"no options provider registered for region {region!r}",
            details={"region_code": region, "broker_code": broker},
        ), 503
    return (provider, region), None, None


def _serialize_contract(c: Any) -> dict[str, Any]:
    return {
        "underlying": c.underlying,
        "expiry": c.expiry.isoformat(),
        "right": c.right.value if hasattr(c.right, "value") else str(c.right),
        "strike": str(c.strike),
        "lot_size": int(c.lot_size),
        "multiplier": int(c.multiplier),
        "currency": c.currency,
        "venue_code": c.venue_code,
    }


@api_expiries.route("")
@api_expiries.route("/")
class OptionsExpiries(Resource):
    def get(self):
        auth_token, broker, auth_err = resolve_auth()
        if auth_err is not None:
            return error("unauthorized", auth_err), 401

        underlying = (request.args.get("underlying") or "").strip().upper()
        if not underlying:
            return error("bad_request",
                         "underlying query param required"), 400

        asof_str = request.args.get("asof")
        if asof_str:
            try:
                asof = _date.fromisoformat(asof_str)
            except ValueError:
                return error("bad_request",
                             "asof must be YYYY-MM-DD"), 400
        else:
            from datetime import datetime, timezone
            asof = datetime.now(timezone.utc).date()

        resolved, err_payload, err_status = _resolve_options_provider(broker)
        if resolved is None:
            return err_payload, err_status
        provider, region = resolved

        try:
            expiries = provider.list_expiries(underlying, asof)
        except Exception as e:
            logger.exception("options.list_expiries failed: %s", e)
            return error("provider_error", str(e)), 502

        return ok({
            "underlying": underlying,
            "region_code": region,
            "asof": asof.isoformat(),
            "expiries": [d.isoformat() for d in expiries],
        }), 200


@api_chain.route("")
@api_chain.route("/")
class OptionsChain(Resource):
    def get(self):
        auth_token, broker, auth_err = resolve_auth()
        if auth_err is not None:
            return error("unauthorized", auth_err), 401

        underlying = (request.args.get("underlying") or "").strip().upper()
        expiry_str = request.args.get("expiry")
        if not underlying or not expiry_str:
            return error(
                "bad_request",
                "underlying and expiry query params both required",
            ), 400
        try:
            expiry = _date.fromisoformat(expiry_str)
        except ValueError:
            return error("bad_request", "expiry must be YYYY-MM-DD"), 400

        resolved, err_payload, err_status = _resolve_options_provider(broker)
        if resolved is None:
            return err_payload, err_status
        provider, region = resolved

        try:
            chain = provider.get_chain(underlying, expiry)
        except Exception as e:
            logger.exception("options.get_chain failed: %s", e)
            return error("provider_error", str(e)), 502

        return ok({
            "underlying": chain.underlying,
            "expiry": chain.expiry.isoformat(),
            "region_code": region,
            "calls": [_serialize_contract(c) for c in chain.calls],
            "puts": [_serialize_contract(c) for c in chain.puts],
        }), 200
