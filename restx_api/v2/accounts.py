"""GET /api/v2/positions and /api/v2/balances.

Two separate flask-restx namespaces so each lives directly under
`/api/v2/` rather than a shared `accounts/` prefix. Skeleton
implementations — they proxy to the existing v1 services and wrap the
response in the v2 envelope.
"""

from __future__ import annotations

from flask_restx import Namespace, Resource

from restx_api.v2._auth import error, ok, resolve_auth
from utils.logging import get_logger

logger = get_logger(__name__)

positions_api = Namespace("positions", description="Normalized position view")
balances_api = Namespace("balances", description="Normalized balance view")


@positions_api.route("")
@positions_api.route("/")
class Positions(Resource):
    def get(self):
        auth_token, broker, auth_err = resolve_auth()
        if auth_err is not None:
            return error("unauthorized", auth_err), 401

        try:
            from services.positions_service import get_positions_with_auth
        except Exception as e:
            return error("unimplemented",
                         f"positions service not available: {e}"), 501

        ok_flag, resp, status = get_positions_with_auth(
            auth_token=auth_token, broker=broker
        )
        if not ok_flag:
            return error("broker_error",
                         resp.get("message", "positions fetch failed")), status

        rows = resp.get("data", [])
        return ok({"positions": rows}), 200


@balances_api.route("")
@balances_api.route("/")
class Balances(Resource):
    def get(self):
        auth_token, broker, auth_err = resolve_auth()
        if auth_err is not None:
            return error("unauthorized", auth_err), 401

        try:
            from services.funds_service import get_funds_with_auth
        except Exception as e:
            return error("unimplemented",
                         f"funds service not available: {e}"), 501

        ok_flag, resp, status = get_funds_with_auth(
            auth_token=auth_token, broker=broker
        )
        if not ok_flag:
            return error("broker_error", resp.get("message", "funds fetch failed")), status

        return ok({"balances": resp.get("data", {})}), 200
