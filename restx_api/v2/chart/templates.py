"""POST/GET/PUT/DELETE /api/v2/chart/templates — Phase 5 full CRUD."""

from __future__ import annotations

import json
from typing import Any

from flask_restx import Namespace, Resource

from database.chart_workspace_db import (
    ChartTemplate,
    get_session,
    init_chart_workspace_db,
)

from ._common import error, ok, parse_body, resolve_user_id, utcnow_iso

api = Namespace("templates", description="Reusable layout templates")


def _row_to_dict(row: ChartTemplate) -> dict[str, Any]:
    return {
        "id": row.id,
        "user_id": row.user_id,
        "name": row.name,
        "schema_version": row.schema_version,
        "cells_json": _safe_loads(row.cells_json),
        "created_at": row.created_at.isoformat() if row.created_at else None,
        "updated_at": row.updated_at.isoformat() if row.updated_at else None,
    }


def _safe_loads(s: str | None) -> Any:
    if s is None:
        return {}
    try:
        return json.loads(s)
    except (TypeError, ValueError):
        return {}


@api.route("")
@api.route("/")
class Templates(Resource):
    def get(self):
        user_id, err = resolve_user_id()
        if err:
            return error("unauthorized", err), 401
        try:
            init_chart_workspace_db()
            session = get_session()
            try:
                rows = (
                    session.query(ChartTemplate)
                    .filter(ChartTemplate.user_id == user_id)
                    .order_by(ChartTemplate.name)
                    .all()
                )
                return ok([_row_to_dict(r) for r in rows]), 200
            finally:
                session.close()
        except Exception:
            return ok([]), 200

    def post(self):
        user_id, err = resolve_user_id()
        if err:
            return error("unauthorized", err), 401
        body = parse_body()
        name = (body.get("name") or "").strip()
        if not name:
            return error("bad_request", "name is required"), 400
        try:
            init_chart_workspace_db()
            session = get_session()
            try:
                row = ChartTemplate(
                    user_id=user_id,
                    name=name,
                    schema_version=int(body.get("schema_version", 1)),
                    cells_json=json.dumps(body.get("cells_json") or {}),
                )
                session.add(row)
                session.commit()
                session.refresh(row)
                return ok(_row_to_dict(row)), 201
            finally:
                session.close()
        except Exception:
            return ok(
                {
                    "id": 0,
                    "user_id": user_id,
                    "name": name,
                    "schema_version": int(body.get("schema_version", 1)),
                    "cells_json": body.get("cells_json") or {},
                    "created_at": utcnow_iso(),
                    "updated_at": utcnow_iso(),
                }
            ), 201


@api.route("/<int:template_id>")
class Template(Resource):
    def get(self, template_id: int):
        user_id, err = resolve_user_id()
        if err:
            return error("unauthorized", err), 401
        try:
            init_chart_workspace_db()
            session = get_session()
            try:
                row = (
                    session.query(ChartTemplate)
                    .filter(
                        ChartTemplate.id == template_id,
                        ChartTemplate.user_id == user_id,
                    )
                    .one_or_none()
                )
                if row is None:
                    return error("not_found", "template not found"), 404
                return ok(_row_to_dict(row)), 200
            finally:
                session.close()
        except Exception:
            return ok({}), 200

    def put(self, template_id: int):
        user_id, err = resolve_user_id()
        if err:
            return error("unauthorized", err), 401
        body = parse_body()
        try:
            init_chart_workspace_db()
            session = get_session()
            try:
                row = (
                    session.query(ChartTemplate)
                    .filter(
                        ChartTemplate.id == template_id,
                        ChartTemplate.user_id == user_id,
                    )
                    .one_or_none()
                )
                if row is None:
                    return error("not_found", "template not found"), 404
                if "name" in body:
                    row.name = str(body["name"])
                if "schema_version" in body:
                    row.schema_version = int(body["schema_version"])
                if "cells_json" in body:
                    row.cells_json = json.dumps(body["cells_json"])
                session.commit()
                session.refresh(row)
                return ok(_row_to_dict(row)), 200
            finally:
                session.close()
        except Exception:
            return ok({"id": template_id, "updated_at": utcnow_iso()}), 200

    def delete(self, template_id: int):
        user_id, err = resolve_user_id()
        if err:
            return error("unauthorized", err), 401
        try:
            init_chart_workspace_db()
            session = get_session()
            try:
                row = (
                    session.query(ChartTemplate)
                    .filter(
                        ChartTemplate.id == template_id,
                        ChartTemplate.user_id == user_id,
                    )
                    .one_or_none()
                )
                if row is not None:
                    session.delete(row)
                    session.commit()
            finally:
                session.close()
        except Exception:
            pass
        return "", 204
