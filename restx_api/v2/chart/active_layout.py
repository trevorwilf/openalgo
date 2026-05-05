"""GET/PUT /api/v2/chart/active-layout — Phase 1 skeleton."""

from __future__ import annotations

from flask_restx import Namespace, Resource

from ._common import error, ok, parse_body, resolve_user_id, utcnow_iso

api = Namespace("active-layout", description="Current active layout pointer")


@api.route("")
@api.route("/")
class ActiveLayout(Resource):
    def get(self):
        user_id, err = resolve_user_id()
        if err:
            return error("unauthorized", err), 401
        return ok({"user_id": user_id, "layout_id": None, "updated_at": None}), 200

    def put(self):
        user_id, err = resolve_user_id()
        if err:
            return error("unauthorized", err), 401
        body = parse_body()
        return ok(
            {
                "user_id": user_id,
                "layout_id": body.get("layout_id"),
                "updated_at": utcnow_iso(),
            }
        ), 200
