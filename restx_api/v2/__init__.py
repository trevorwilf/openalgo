"""Phase 6 /api/v2 skeleton.

`/api/v2` exposes the Phase 1a normalized DTOs directly. `/api/v1`
remains untouched — every v1 endpoint continues to emit its current
Indian-shaped payloads byte-for-byte.

Gating
------
The blueprint is only created + registered when ``API_V2`` is
enabled. When the flag is off, `register_api_v2` is a no-op and every
``/api/v2/*`` request returns 404 from Flask's default routing — which
is exactly what the playbook's ``test_flag_off.py`` asserts.

Scope
-----
This is a SKELETON. Endpoints return normalized shapes but most wrap
existing v1 services (quotes, history, orderbook) for their data and
translate in/out via ``domain.translators``. This gives us a stable
external surface without touching any broker module.

Authentication / authorization
------------------------------
v2 endpoints reuse the same ``apikey`` auth as v1 via
``get_auth_token_broker``. No new auth mechanism is introduced.
"""

from __future__ import annotations

from typing import Optional

from flask import Blueprint
from flask_restx import Api

from utils.feature_flags import is_enabled
from utils.logging import get_logger

logger = get_logger(__name__)


# Populated at registration time. Kept at module level so tests that
# exercise the blueprint directly can import it.
api_v2_bp: Optional[Blueprint] = None
api_v2: Optional[Api] = None


def _build() -> tuple[Blueprint, Api]:
    bp = Blueprint("api_v2", __name__, url_prefix="/api/v2")
    api = Api(
        bp,
        version="2.0",
        title="OpenAlgo API v2",
        description=(
            "Market-agnostic API — Phase 6 skeleton. Normalized DTOs, "
            "InstrumentRef-based resolution, dual-read legacy path when "
            "the Phase 2a instrument universe is empty."
        ),
        doc=False,
    )

    from restx_api.v2.accounts import balances_api, positions_api
    from restx_api.v2.bars import api as bars_ns
    from restx_api.v2.broker_compliance import api as broker_compliance_ns
    from restx_api.v2.capabilities import api as capabilities_ns
    from restx_api.v2.chart import (
        active_layout_ns,
        drawings_ns,
        indicators_ns,
        layouts_ns,
        templates_ns,
        watchlists_ns,
    )
    from restx_api.v2.chart_audit import api as audit_ns
    from restx_api.v2.indicators_series import api as indicators_series_ns
    from restx_api.v2.instruments import api as instruments_ns
    from restx_api.v2.holdings import api as holdings_ns
    from restx_api.v2.orders import api as orders_ns
    from restx_api.v2.trades import api as trades_ns
    from restx_api.v2.strategy_signals import api as strategy_signals_ns
    from restx_api.v2.orders_combo import api as orders_combo_ns
    from restx_api.v2.plugins import api as plugins_ns
    from restx_api.v2.quotes import api as quotes_ns
    from restx_api.v2.regions import api as regions_ns
    from restx_api.v2.venues import api as venues_ns

    api.add_namespace(capabilities_ns, path="/capabilities")
    api.add_namespace(instruments_ns, path="/instruments")
    api.add_namespace(quotes_ns, path="/quotes")
    api.add_namespace(bars_ns, path="/bars")
    api.add_namespace(orders_ns, path="/orders")
    api.add_namespace(orders_combo_ns, path="/orders/combo")
    api.add_namespace(trades_ns, path="/trades")
    api.add_namespace(holdings_ns, path="/holdings")
    api.add_namespace(positions_api, path="/positions")
    api.add_namespace(balances_api, path="/balances")
    api.add_namespace(venues_ns, path="/venues")
    api.add_namespace(regions_ns, path="/regions")
    api.add_namespace(plugins_ns, path="/plugins")
    # /api/v2/chart/* sub-namespaces (Phase 1 skeleton; Phase 5 wires CRUD).
    api.add_namespace(layouts_ns, path="/chart/layouts")
    api.add_namespace(drawings_ns, path="/chart/drawings")
    api.add_namespace(indicators_ns, path="/chart/indicators")
    api.add_namespace(watchlists_ns, path="/chart/watchlists")
    api.add_namespace(templates_ns, path="/chart/templates")
    api.add_namespace(active_layout_ns, path="/chart/active-layout")
    api.add_namespace(indicators_series_ns, path="/indicators/series")
    api.add_namespace(audit_ns, path="/audit/chart-orders")
    api.add_namespace(strategy_signals_ns, path="/strategy-signals")
    api.add_namespace(broker_compliance_ns, path="/admin/broker_compliance")

    return bp, api


def register_api_v2(app) -> bool:
    """Register the /api/v2 blueprint on `app` if API_V2 is enabled.

    Returns True if the blueprint was registered, False if gated off.
    Always builds a fresh blueprint for the given `app` — tests create
    a new Flask app per test, and production calls this exactly once
    from `create_app`. The module-level `api_v2_bp` / `api_v2` are the
    most recently registered instances, exposed so app.py can CSRF-
    exempt them.
    """
    global api_v2_bp, api_v2
    if not is_enabled("API_V2"):
        logger.debug("API_V2 flag off; /api/v2 not registered")
        return False

    bp, api = _build()
    app.register_blueprint(bp)

    api_v2_bp = bp
    api_v2 = api
    logger.info("/api/v2 skeleton registered (API_V2=1)")
    return True


__all__ = ["api_v2", "api_v2_bp", "register_api_v2"]
