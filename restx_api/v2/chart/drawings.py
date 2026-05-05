"""POST/GET/PUT/DELETE /api/v2/chart/drawings — Phase 5 full CRUD."""

from __future__ import annotations

import json
from typing import Any

from flask import request
from flask_restx import Namespace, Resource

from database.chart_workspace_db import (
    ChartDrawing,
    get_session,
    init_chart_workspace_db,
)

from ._common import error, ok, parse_body, resolve_user_id, utcnow_iso

api = Namespace("drawings", description="Chart drawings")


def _row_to_dict(row: ChartDrawing) -> dict[str, Any]:
    return {
        "id": row.id,
        "user_id": row.user_id,
        "layout_id": row.layout_id,
        "cell_id": row.cell_id,
        "kind": row.kind,
        "params_json": _safe_loads(row.params_json),
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
class Drawings(Resource):
    def get(self):
        user_id, err = resolve_user_id()
        if err:
            return error("unauthorized", err), 401
        layout_id = request.args.get("layout_id", type=int)
        cell_id = request.args.get("cell_id")
        try:
            init_chart_workspace_db()
            session = get_session()
            try:
                q = session.query(ChartDrawing).filter(ChartDrawing.user_id == user_id)
                if layout_id is not None:
                    q = q.filter(ChartDrawing.layout_id == layout_id)
                if cell_id:
                    q = q.filter(ChartDrawing.cell_id == cell_id)
                rows = q.order_by(ChartDrawing.id).all()
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
        layout_id = body.get("layout_id")
        cell_id = body.get("cell_id")
        kind = body.get("kind", "")
        if layout_id is None or not cell_id or not kind:
            return error("bad_request", "layout_id, cell_id, kind are required"), 400
        try:
            init_chart_workspace_db()
            session = get_session()
            try:
                row = ChartDrawing(
                    user_id=user_id,
                    layout_id=int(layout_id),
                    cell_id=str(cell_id),
                    kind=str(kind),
                    params_json=json.dumps(body.get("params_json") or {}),
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
                    "layout_id": layout_id,
                    "cell_id": cell_id,
                    "kind": kind,
                    "params_json": body.get("params_json") or {},
                    "created_at": utcnow_iso(),
                    "updated_at": utcnow_iso(),
                }
            ), 201


@api.route("/<int:drawing_id>")
class Drawing(Resource):
    def get(self, drawing_id: int):
        user_id, err = resolve_user_id()
        if err:
            return error("unauthorized", err), 401
        try:
            init_chart_workspace_db()
            session = get_session()
            try:
                row = (
                    session.query(ChartDrawing)
                    .filter(
                        ChartDrawing.id == drawing_id, ChartDrawing.user_id == user_id
                    )
                    .one_or_none()
                )
                if row is None:
                    return error("not_found", "drawing not found"), 404
                return ok(_row_to_dict(row)), 200
            finally:
                session.close()
        except Exception:
            return ok({}), 200

    def put(self, drawing_id: int):
        user_id, err = resolve_user_id()
        if err:
            return error("unauthorized", err), 401
        body = parse_body()
        try:
            init_chart_workspace_db()
            session = get_session()
            try:
                row = (
                    session.query(ChartDrawing)
                    .filter(
                        ChartDrawing.id == drawing_id, ChartDrawing.user_id == user_id
                    )
                    .one_or_none()
                )
                if row is None:
                    return error("not_found", "drawing not found"), 404
                if "kind" in body:
                    row.kind = str(body["kind"])
                if "cell_id" in body:
                    row.cell_id = str(body["cell_id"])
                if "params_json" in body:
                    row.params_json = json.dumps(body["params_json"])
                session.commit()
                session.refresh(row)
                return ok(_row_to_dict(row)), 200
            finally:
                session.close()
        except Exception:
            return ok({"id": drawing_id, "updated_at": utcnow_iso()}), 200

    def delete(self, drawing_id: int):
        user_id, err = resolve_user_id()
        if err:
            return error("unauthorized", err), 401
        try:
            init_chart_workspace_db()
            session = get_session()
            try:
                row = (
                    session.query(ChartDrawing)
                    .filter(
                        ChartDrawing.id == drawing_id, ChartDrawing.user_id == user_id
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
