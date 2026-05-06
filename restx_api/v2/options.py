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
api_greeks = Namespace("options_greeks",
                        description="Black-Scholes Greeks for one option contract")
api_symbol = Namespace("options_symbol",
                        description="Parse and format option symbols per region")


def _resolve_options_provider(broker: str | None):
    """Return ``((provider, region_code), error_payload, http_status)``.

    Resolves the region from the apikey-resolved broker's plugin
    capabilities (``supported_regions[0]``) directly, NOT via
    ``services.feature_gate_service.active_region_code`` which reads
    Flask session — that reader returns None for apikey-authenticated
    callers and falls through to the settings default (usually
    "india"), masking the real region for non-India brokers like
    Alpaca.
    """
    from services.options.dispatcher import get_options_provider_or_none

    if not broker:
        return None, error(
            "missing_region_context",
            "could not resolve broker — apikey did not bind to a broker",
        ), 503

    try:
        from utils.plugin_loader import get_broker_capabilities
        caps = get_broker_capabilities(broker)
    except Exception:
        caps = None
    regions = list(getattr(caps, "supported_regions", None) or [])
    if not regions:
        return None, error(
            "missing_region_context",
            f"broker {broker!r} has no supported_regions in plugin capabilities",
            details={"broker_code": broker},
        ), 503
    region = str(regions[0]).strip().lower()

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


@api_greeks.route("")
@api_greeks.route("/")
class OptionsGreeks(Resource):
    """GET /api/v2/options/greeks — Black-Scholes Greeks per contract.

    Required query params:
        underlying  — underlying symbol (case-insensitive)
        expiry      — YYYY-MM-DD
        strike      — decimal string
        right       — CALL or PUT
        spot        — current underlying price (decimal string)
        iv          — implied vol (decimal string, e.g. "0.35" for 35%)

    Optional:
        risk_free_rate     (default 0.05)
        dividend_yield     (default 0)

    Response:
        {"data": {"underlying": ..., "expiry": ..., "strike": ...,
                  "right": "CALL", "region_code": "us",
                  "delta": "0.5234", "gamma": "0.0123",
                  "theta": "-0.0456", "vega": "0.1234",
                  "rho": "0.0789"}}
    """

    def get(self):
        from datetime import date as _date
        from decimal import Decimal, InvalidOperation

        from domain.options import MarketSnapshot, OptionContract, OptionRight

        auth_token, broker, auth_err = resolve_auth()
        if auth_err is not None:
            return error("unauthorized", auth_err), 401

        try:
            underlying = (request.args.get("underlying") or "").strip().upper()
            expiry_str = request.args.get("expiry")
            strike_str = request.args.get("strike")
            right_str = (request.args.get("right") or "").strip().upper()
            spot_str = request.args.get("spot")
            iv_str = request.args.get("iv")
            for label, val in [("underlying", underlying), ("expiry", expiry_str),
                               ("strike", strike_str), ("right", right_str),
                               ("spot", spot_str), ("iv", iv_str)]:
                if not val:
                    return error("bad_request",
                                 f"{label} query param required"), 400
            expiry = _date.fromisoformat(expiry_str)
            strike = Decimal(strike_str)
            spot = Decimal(spot_str)
            iv = Decimal(iv_str)
            if right_str not in ("CALL", "PUT"):
                return error("bad_request",
                             "right must be CALL or PUT"), 400
            risk_free = Decimal(request.args.get("risk_free_rate") or "0.05")
            div_yield = Decimal(request.args.get("dividend_yield") or "0")
            asof_str = request.args.get("asof")
            if asof_str:
                asof = _date.fromisoformat(asof_str)
            else:
                from datetime import datetime as _dt, timezone as _tz
                asof = _dt.now(_tz.utc).date()
        except (ValueError, InvalidOperation) as e:
            return error("bad_request", f"could not parse params: {e}"), 400

        resolved, err_payload, err_status = _resolve_options_provider(broker)
        if resolved is None:
            return err_payload, err_status
        provider, region = resolved

        # Provider's get_chain shape would have lot_size / multiplier /
        # currency / venue_code per region — we don't actually need those
        # to compute Greeks (only strike, right, expiry matter). Use the
        # same shape so the contract is consistent.
        try:
            sample = provider.get_chain(underlying, expiry).calls[:1]
        except Exception:
            sample = []
        defaults = {
            "lot_size": sample[0].lot_size if sample else 100,
            "multiplier": sample[0].multiplier if sample else 100,
            "currency": sample[0].currency if sample else "USD",
            "venue_code": sample[0].venue_code if sample else "OPRA",
        }
        contract = OptionContract(
            underlying=underlying, expiry=expiry,
            right=OptionRight.CALL if right_str == "CALL" else OptionRight.PUT,
            strike=strike, lot_size=defaults["lot_size"],
            multiplier=defaults["multiplier"],
            currency=defaults["currency"], venue_code=defaults["venue_code"],
        )
        market = MarketSnapshot(
            underlying_price=spot,
            risk_free_rate=risk_free,
            dividend_yield=div_yield,
            asof=asof,
        )

        try:
            greeks = provider.compute_greeks(contract, market, iv)
        except Exception as e:
            logger.exception("options.compute_greeks failed: %s", e)
            return error("provider_error", str(e)), 502

        return ok({
            "underlying": underlying,
            "expiry": expiry.isoformat(),
            "strike": str(strike),
            "right": right_str,
            "region_code": region,
            "spot": str(spot),
            "iv": str(iv),
            "delta": str(greeks.delta),
            "gamma": str(greeks.gamma),
            "theta": str(greeks.theta),
            "vega": str(greeks.vega),
            "rho": str(greeks.rho) if greeks.rho is not None else None,
        }), 200


@api_symbol.route("")
@api_symbol.route("/")
class OptionsSymbol(Resource):
    """GET /api/v2/options/symbol — parse/format option symbols.

    Modes:
      mode=parse: query symbol=AAPL240419C00185000 → underlying / expiry / right / strike
      mode=format: query underlying / expiry / right / strike → symbol
    """

    def get(self):
        from datetime import date as _date
        from decimal import Decimal, InvalidOperation

        from domain.options import OptionContract, OptionRight

        auth_token, broker, auth_err = resolve_auth()
        if auth_err is not None:
            return error("unauthorized", auth_err), 401

        resolved, err_payload, err_status = _resolve_options_provider(broker)
        if resolved is None:
            return err_payload, err_status
        provider, region = resolved

        mode = (request.args.get("mode") or "").strip().lower()
        if mode == "parse":
            symbol = request.args.get("symbol") or ""
            if not symbol:
                return error("bad_request",
                             "symbol query param required when mode=parse"), 400
            try:
                contract = provider.parse_option_symbol(symbol)
            except Exception as e:
                return error("parse_error", str(e)), 400
            return ok({
                "mode": "parse",
                "region_code": region,
                "symbol": symbol,
                "underlying": contract.underlying.strip(),
                "expiry": contract.expiry.isoformat(),
                "right": contract.right.value if hasattr(contract.right, "value") else str(contract.right),
                "strike": str(contract.strike),
            }), 200
        elif mode == "format":
            try:
                underlying = (request.args.get("underlying") or "").strip().upper()
                expiry_str = request.args.get("expiry")
                strike_str = request.args.get("strike")
                right_str = (request.args.get("right") or "").strip().upper()
                if not (underlying and expiry_str and strike_str and right_str):
                    return error(
                        "bad_request",
                        "underlying, expiry, strike, right all required when mode=format",
                    ), 400
                expiry = _date.fromisoformat(expiry_str)
                strike = Decimal(strike_str)
                if right_str not in ("CALL", "PUT"):
                    return error("bad_request",
                                 "right must be CALL or PUT"), 400
            except (ValueError, InvalidOperation) as e:
                return error("bad_request", f"could not parse params: {e}"), 400

            # Take lot_size/multiplier/currency/venue from a sample chain
            # contract for the region (provider knows its own shape).
            try:
                sample = provider.get_chain(underlying, expiry).calls[:1]
            except Exception:
                sample = []
            contract = OptionContract(
                underlying=underlying, expiry=expiry,
                right=OptionRight.CALL if right_str == "CALL" else OptionRight.PUT,
                strike=strike,
                lot_size=sample[0].lot_size if sample else 100,
                multiplier=sample[0].multiplier if sample else 100,
                currency=sample[0].currency if sample else "USD",
                venue_code=sample[0].venue_code if sample else "OPRA",
            )
            try:
                symbol = provider.format_option_symbol(contract)
            except Exception as e:
                return error("format_error", str(e)), 400
            return ok({
                "mode": "format",
                "region_code": region,
                "symbol": symbol,
                "underlying": underlying,
                "expiry": expiry.isoformat(),
                "right": right_str,
                "strike": str(strike),
            }), 200
        else:
            return error(
                "bad_request",
                "mode query param must be 'parse' or 'format'",
            ), 400


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
