from flask import Blueprint, jsonify, request
from flask_restx import Api

api_v1_bp = Blueprint("api_v1", __name__, url_prefix="/api/v1")
api = Api(
    api_v1_bp,
    version="1.0",
    title="OpenAlgo API",
    description="API for OpenAlgo Trading Platform",
    doc=False,
)


# Phase 2 v4 (ADR 0023, invariant 5) — v1 hard-block for non-India brokers.
# Every /api/v1/* request runs through this guard. India brokers
# proceed unchanged; non-India brokers receive a structured 410 Gone
# with code v1_unavailable_for_non_india_broker.
# Phase 9-bis-physical (T-23 Group D) — guard relocated to
# market_regions.india.legacy_v1.restx_api._v1_lane_guard.
from market_regions.india.legacy_v1.restx_api._v1_lane_guard import (
    enforce_india_only as _v1_enforce_india_only,
)


# v5 Phase 8 (D-1) — v1 deprecation announcement via response headers.
# Every /api/v1/* response carries `Deprecation: true` and a `Sunset`
# date. Operators control the actual sunset via the env var
# OPENALGO_V1_SUNSET_DATE (ISO 8601). The default is `now + 180 days`
# so a fresh deployment always advertises an explicit sunset date.
import os
from datetime import date, datetime, timedelta, timezone


def _v1_sunset_date_iso() -> str:
    raw = os.getenv("OPENALGO_V1_SUNSET_DATE")
    if raw:
        return raw.strip()
    return (datetime.now(timezone.utc) + timedelta(days=180)).date().isoformat()


def _v1_explicitly_sunset_date() -> "date | None":
    """Phase 9 (T-33) — return the operator-configured sunset date or
    ``None``. The env var is the operator's actual cutover date; when
    it is unset the v1 lane stays alive indefinitely (the
    ``Sunset:`` header still advertises a default 180-day window per
    v5 Phase 8, but no enforcement happens). When set, requests after
    that date receive a 410 Gone for every region (including India).
    """
    raw = os.getenv("OPENALGO_V1_SUNSET_DATE")
    if not raw:
        return None
    try:
        return date.fromisoformat(raw.strip())
    except ValueError:
        return None


@api_v1_bp.before_request
def _v1_block_non_india_brokers_or_sunset():
    # Phase 9 (T-33) — operator-controlled hard sunset. If the env
    # var is set and today is past that date, every /api/v1/* request
    # returns 410 Gone with code ``v1_sunset_passed`` regardless of
    # broker region. Skipping for swagger / openapi documentation
    # endpoints — they are introspection routes that don't carry
    # trading semantics.
    sunset = _v1_explicitly_sunset_date()
    if sunset is not None and datetime.now(timezone.utc).date() >= sunset:
        path = (request.path or "")
        if not (path.endswith("/swagger.json") or path.endswith("/swaggerui")):
            payload = {
                "status": "error",
                "code": "v1_sunset_passed",
                "message": (
                    f"/api/v1/* was sunset on {sunset.isoformat()}; the "
                    "endpoint is no longer available. Migrate to "
                    "/api/v2/*. See https://docs.openalgo.in/migration/v1-to-v2."
                ),
                "sunset_date": sunset.isoformat(),
            }
            return jsonify(payload), 410
    # Phase 2 v4 (ADR 0023, invariant 5) — v1 hard-block for non-India
    # brokers. India brokers proceed unchanged; non-India brokers
    # receive a structured 410 Gone with code
    # ``v1_unavailable_for_non_india_broker``.
    return _v1_enforce_india_only()


@api_v1_bp.after_request
def _v1_deprecation_headers(response):
    # RFC 8594-aligned: Deprecation: true + Sunset: HTTP-date.
    # The Sunset header carries an ISO date for clarity (most clients
    # will not parse the strict HTTP-date format).
    response.headers["Deprecation"] = "true"
    response.headers["Sunset"] = _v1_sunset_date_iso()
    response.headers.setdefault("Link", '<https://docs.openalgo.in/migration/v1-to-v2>; rel="deprecation"')
    return response

# Import namespaces. Phase 9-bis-physical (T-23 Group C) — endpoint
# modules now live under ``market_regions.india.legacy_v1.restx_api.*``;
# the ``api_v1_bp`` Blueprint + namespace registrations stay here so
# ``app.py``'s ``from restx_api import api_v1_bp`` import remains
# stable.
from market_regions.india.legacy_v1.restx_api.analyzer import api as analyzer_ns
from market_regions.india.legacy_v1.restx_api.basket_order import api as basket_order_ns
from market_regions.india.legacy_v1.restx_api.cancel_all_order import api as cancel_all_order_ns
from market_regions.india.legacy_v1.restx_api.cancel_order import api as cancel_order_ns
from market_regions.india.legacy_v1.restx_api.chart_api import api as chart_ns
from market_regions.india.legacy_v1.restx_api.close_position import api as close_position_ns
from market_regions.india.legacy_v1.restx_api.depth import api as depth_ns
from market_regions.india.legacy_v1.restx_api.expiry import api as expiry_ns
from market_regions.india.legacy_v1.restx_api.funds import api as funds_ns
from market_regions.india.legacy_v1.restx_api.history import api as history_ns
from market_regions.india.legacy_v1.restx_api.holdings import api as holdings_ns
from market_regions.india.legacy_v1.restx_api.instruments import api as instruments_ns
from market_regions.india.legacy_v1.restx_api.intervals import api as intervals_ns
from market_regions.india.legacy_v1.restx_api.margin import api as margin_ns
from market_regions.india.legacy_v1.restx_api.market_holidays import api as market_holidays_ns
from market_regions.india.legacy_v1.restx_api.market_timings import api as market_timings_ns
from market_regions.india.legacy_v1.restx_api.modify_order import api as modify_order_ns
from market_regions.india.legacy_v1.restx_api.multi_option_greeks import api as multi_option_greeks_ns
from market_regions.india.legacy_v1.restx_api.multiquotes import api as multiquotes_ns
from market_regions.india.legacy_v1.restx_api.openposition import api as openposition_ns
from market_regions.india.legacy_v1.restx_api.option_chain import api as option_chain_ns
from market_regions.india.legacy_v1.restx_api.option_greeks import api as option_greeks_ns
from market_regions.india.legacy_v1.restx_api.option_symbol import api as option_symbol_ns
from market_regions.india.legacy_v1.restx_api.options_multiorder import api as options_multiorder_ns
from market_regions.india.legacy_v1.restx_api.options_order import api as options_order_ns
from market_regions.india.legacy_v1.restx_api.orderbook import api as orderbook_ns
from market_regions.india.legacy_v1.restx_api.orderstatus import api as orderstatus_ns
from market_regions.india.legacy_v1.restx_api.ping import api as ping_ns
from market_regions.india.legacy_v1.restx_api.place_order import api as place_order_ns
from market_regions.india.legacy_v1.restx_api.place_smart_order import api as place_smart_order_ns
from market_regions.india.legacy_v1.restx_api.pnl_symbols import api as pnl_symbols_ns
from market_regions.india.legacy_v1.restx_api.positionbook import api as positionbook_ns
from market_regions.india.legacy_v1.restx_api.quotes import api as quotes_ns
from market_regions.india.legacy_v1.restx_api.search import api as search_ns
from market_regions.india.legacy_v1.restx_api.split_order import api as split_order_ns
from market_regions.india.legacy_v1.restx_api.symbol import api as symbol_ns
from market_regions.india.legacy_v1.restx_api.synthetic_future import api as synthetic_future_ns
from market_regions.india.legacy_v1.restx_api.telegram_bot import api as telegram_ns
from market_regions.india.legacy_v1.restx_api.ticker import api as ticker_ns
from market_regions.india.legacy_v1.restx_api.tradebook import api as tradebook_ns

# Add namespaces
api.add_namespace(place_order_ns, path="/placeorder")
api.add_namespace(place_smart_order_ns, path="/placesmartorder")
api.add_namespace(modify_order_ns, path="/modifyorder")
api.add_namespace(cancel_order_ns, path="/cancelorder")
api.add_namespace(close_position_ns, path="/closeposition")
api.add_namespace(cancel_all_order_ns, path="/cancelallorder")
api.add_namespace(quotes_ns, path="/quotes")
api.add_namespace(multiquotes_ns, path="/multiquotes")
api.add_namespace(history_ns, path="/history")
api.add_namespace(depth_ns, path="/depth")
api.add_namespace(option_chain_ns, path="/optionchain")
api.add_namespace(intervals_ns, path="/intervals")
api.add_namespace(funds_ns, path="/funds")
api.add_namespace(orderbook_ns, path="/orderbook")
api.add_namespace(tradebook_ns, path="/tradebook")
api.add_namespace(positionbook_ns, path="/positionbook")
api.add_namespace(holdings_ns, path="/holdings")
api.add_namespace(basket_order_ns, path="/basketorder")
api.add_namespace(split_order_ns, path="/splitorder")
api.add_namespace(orderstatus_ns, path="/orderstatus")
api.add_namespace(openposition_ns, path="/openposition")
api.add_namespace(ticker_ns, path="/ticker")
api.add_namespace(symbol_ns, path="/symbol")
api.add_namespace(search_ns, path="/search")
api.add_namespace(expiry_ns, path="/expiry")
api.add_namespace(option_symbol_ns, path="/optionsymbol")
api.add_namespace(options_order_ns, path="/optionsorder")
api.add_namespace(options_multiorder_ns, path="/optionsmultiorder")
api.add_namespace(option_greeks_ns, path="/optiongreeks")
api.add_namespace(multi_option_greeks_ns, path="/multioptiongreeks")
api.add_namespace(synthetic_future_ns, path="/syntheticfuture")
api.add_namespace(analyzer_ns, path="/analyzer")
api.add_namespace(ping_ns, path="/ping")
api.add_namespace(telegram_ns, path="/telegram")
api.add_namespace(margin_ns, path="/margin")
api.add_namespace(instruments_ns, path="/instruments")
api.add_namespace(chart_ns, path="/chart")
api.add_namespace(market_holidays_ns, path="/market/holidays")
api.add_namespace(market_timings_ns, path="/market/timings")
api.add_namespace(pnl_symbols_ns, path="/pnl")
