"""GET /api/v2/bars/intervals — supported timeframes for the active broker.

Documented in ``docs/migration/v1-to-v2.md`` as "both lanes live" but
the v2 route was never registered. The legacy
``POST /api/v1/intervals`` returns the categorized interval list
(minutes / hours / days) read from each broker module's
``BrokerData.timeframe_map``. This v2 route exposes the same data.

For Alpaca this resolves to the keys in
``broker.alpaca.api.bar_api._TIMEFRAME_MAP`` plus the legacy ``D``
alias. For Indian brokers it resolves to that broker's per-module map.
"""
from __future__ import annotations

from flask_restx import Namespace, Resource

from restx_api.v2._auth import error, ok, resolve_auth
from utils.logging import get_logger

logger = get_logger(__name__)

api = Namespace("bars_intervals", description="Supported bar intervals")


@api.route("")
@api.route("/")
class BarsIntervals(Resource):
    def get(self):
        auth_token, broker, auth_err = resolve_auth()
        if auth_err is not None:
            return error("unauthorized", auth_err), 401

        # Reuse the legacy intervals service — it's already broker-
        # agnostic (delegates to the broker module's
        # ``BrokerData.timeframe_map``) and returns the canonical
        # categorized shape.
        from services.intervals_service import get_intervals_with_auth

        ok_flag, resp, status = get_intervals_with_auth(
            auth_token=auth_token, broker=broker,
        )
        if not ok_flag:
            return error(
                "broker_error",
                resp.get("message", "intervals fetch failed"),
                details=resp,
            ), status

        # ``get_intervals_with_auth`` returns the legacy India-shaped
        # ``{"status": "success", "data": {...}}``. Strip the legacy
        # status wrapper and re-emit under the v2 envelope.
        data = resp.get("data") or {}
        return ok({"intervals": data, "broker_code": broker}), 200
