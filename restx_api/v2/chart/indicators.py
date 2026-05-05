"""POST/GET/PUT/DELETE /api/v2/chart/indicators — Phase 1 skeleton."""

from __future__ import annotations

from flask_restx import Namespace, Resource

from ._common import error, ok, parse_body, resolve_user_id, utcnow_iso

api = Namespace("indicators", description="Per-cell indicator configurations")


@api.route("")
@api.route("/")
class Indicators(Resource):
    def get(self):
        user_id, err = resolve_user_id()
        if err:
            return error("unauthorized", err), 401
        return ok([]), 200

    def post(self):
        user_id, err = resolve_user_id()
        if err:
            return error("unauthorized", err), 401
        body = parse_body()
        return ok(
            {
                "id": 0,
                "user_id": user_id,
                "layout_id": body.get("layout_id"),
                "cell_id": body.get("cell_id"),
                "indicator_key": body.get("indicator_key", ""),
                "params_json": body.get("params_json", {}),
                "created_at": utcnow_iso(),
                "updated_at": utcnow_iso(),
            }
        ), 201


@api.route("/<int:indicator_id>")
class Indicator(Resource):
    def put(self, indicator_id: int):
        user_id, err = resolve_user_id()
        if err:
            return error("unauthorized", err), 401
        return ok({"id": indicator_id, "updated_at": utcnow_iso()}), 200

    def delete(self, indicator_id: int):
        user_id, err = resolve_user_id()
        if err:
            return error("unauthorized", err), 401
        return "", 204
