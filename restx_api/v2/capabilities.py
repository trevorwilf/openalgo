"""GET /api/v2/capabilities — rich BrokerCapabilities for the active broker.

Resolves the active broker via the standard ``/api/v2`` auth helper
(API key in body / query / header) so external clients
(TradingView, Excel, MCP server, ops scripts) can reach this
endpoint without first establishing a Flask session. The legacy
``session["broker"]`` short-circuit is kept as a fallback so a
browser-side fetch from the React app still works after a normal
web login (no apikey cookie required).
"""

from __future__ import annotations

from flask import session
from flask_restx import Namespace, Resource

from restx_api.v2._auth import error, ok, resolve_auth
from utils.logging import get_logger

logger = get_logger(__name__)

api = Namespace("capabilities", description="Broker capability surface")


@api.route("")
@api.route("/")
class Capabilities(Resource):
    def get(self):
        from utils.plugin_loader import get_broker_capabilities

        # Prefer the standard v2 auth path (API key) so external
        # callers don't need a session cookie. Fall back to the Flask
        # session for browser-side React calls that haven't passed an
        # apikey.
        _auth_token, broker, _err = resolve_auth()
        if not broker:
            broker = session.get("broker")
        if not broker:
            return error("no_broker", "no broker in session and no apikey provided"), 400

        caps = get_broker_capabilities(broker)
        if caps is None:
            return error("broker_unknown", f"no capabilities for broker {broker!r}"), 404
        return ok(caps.model_dump(mode="json")), 200
