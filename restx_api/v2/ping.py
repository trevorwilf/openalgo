"""GET /api/v2/ping — lightweight health probe.

Documented in ``docs/migration/v1-to-v2.md`` as a "both lanes live"
endpoint, but the v2 namespace was never registered. This file closes
that gap.

No auth required (matches the v1 ``/api/v1/ping`` semantics — the
endpoint is for liveness probes from external monitors / load
balancers, not authenticated callers). Returns:

    {"data": {"status": "ok", "timestamp": "2026-05-06T13:..."}}
"""
from __future__ import annotations

from datetime import datetime, timezone

from flask_restx import Namespace, Resource

from restx_api.v2._auth import ok

api = Namespace("ping", description="Liveness probe")


@api.route("")
@api.route("/")
class Ping(Resource):
    def get(self):
        return ok({
            "status": "ok",
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "version": "2.0",
        }), 200
