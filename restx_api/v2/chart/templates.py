"""POST/GET/PUT/DELETE /api/v2/chart/templates — Phase 1 skeleton."""

from __future__ import annotations

from flask_restx import Namespace, Resource

from ._common import error, ok, parse_body, resolve_user_id, utcnow_iso

api = Namespace("templates", description="Reusable layout templates")


@api.route("")
@api.route("/")
class Templates(Resource):
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
                "name": body.get("name", ""),
                "schema_version": int(body.get("schema_version", 1)),
                "cells_json": body.get("cells_json", {}),
                "created_at": utcnow_iso(),
                "updated_at": utcnow_iso(),
            }
        ), 201


@api.route("/<int:template_id>")
class Template(Resource):
    def put(self, template_id: int):
        user_id, err = resolve_user_id()
        if err:
            return error("unauthorized", err), 401
        return ok({"id": template_id, "updated_at": utcnow_iso()}), 200

    def delete(self, template_id: int):
        user_id, err = resolve_user_id()
        if err:
            return error("unauthorized", err), 401
        return "", 204
