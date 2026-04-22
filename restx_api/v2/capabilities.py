"""GET /api/v2/capabilities — rich BrokerCapabilities for the active broker."""

from __future__ import annotations

from flask import session
from flask_restx import Namespace, Resource

from restx_api.v2._auth import error, ok
from utils.logging import get_logger

logger = get_logger(__name__)

api = Namespace("capabilities", description="Broker capability surface")


@api.route("")
@api.route("/")
class Capabilities(Resource):
    def get(self):
        from utils.plugin_loader import get_broker_capabilities

        broker = session.get("broker")
        if not broker:
            return error("no_broker", "no broker in session"), 400

        caps = get_broker_capabilities(broker)
        if caps is None:
            return error("broker_unknown", f"no capabilities for broker {broker!r}"), 404
        return ok(caps.model_dump(mode="json")), 200
