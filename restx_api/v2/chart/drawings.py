"""POST/GET/PUT/DELETE /api/v2/chart/drawings — Phase 1 skeleton."""

from __future__ import annotations

from flask_restx import Namespace, Resource

from ._common import error, ok, parse_body, resolve_user_id, utcnow_iso

api = Namespace("drawings", description="Chart drawings")


@api.route("")
@api.route("/")
class Drawings(Resource):
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
                "kind": body.get("kind", ""),
                "params_json": body.get("params_json", {}),
                "created_at": utcnow_iso(),
                "updated_at": utcnow_iso(),
            }
        ), 201


@api.route("/<int:drawing_id>")
class Drawing(Resource):
    def put(self, drawing_id: int):
        user_id, err = resolve_user_id()
        if err:
            return error("unauthorized", err), 401
        return ok({"id": drawing_id, "updated_at": utcnow_iso()}), 200

    def delete(self, drawing_id: int):
        user_id, err = resolve_user_id()
        if err:
            return error("unauthorized", err), 401
        return "", 204
