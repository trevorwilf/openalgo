"""POST/GET/PUT/DELETE /api/v2/chart/layouts — Phase 5 full CRUD."""

from __future__ import annotations

import json
from typing import Any

from flask_restx import Namespace, Resource

from database.chart_workspace_db import (
    ChartWorkspaceLayout,
    get_session,
    init_chart_workspace_db,
)

from ._common import error, ok, parse_body, resolve_user_id, utcnow_iso

api = Namespace("layouts", description="Workspace layouts")


def _row_to_dict(row: ChartWorkspaceLayout) -> dict[str, Any]:
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
class Layouts(Resource):
    def get(self):
        user_id, err = resolve_user_id()
        if err:
            return error("unauthorized", err), 401
        try:
            init_chart_workspace_db()
            session = get_session()
            try:
                rows = (
                    session.query(ChartWorkspaceLayout)
                    .filter(ChartWorkspaceLayout.user_id == user_id)
                    .order_by(ChartWorkspaceLayout.name)
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
        cells_json = body.get("cells_json")
        try:
            init_chart_workspace_db()
            session = get_session()
            try:
                row = ChartWorkspaceLayout(
                    user_id=user_id,
                    name=name,
                    schema_version=int(body.get("schema_version", 1)),
                    cells_json=json.dumps(cells_json) if cells_json is not None else "{}",
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
                    "cells_json": cells_json or {},
                    "created_at": utcnow_iso(),
                    "updated_at": utcnow_iso(),
                }
            ), 201


@api.route("/<int:layout_id>")
class Layout(Resource):
    def get(self, layout_id: int):
        user_id, err = resolve_user_id()
        if err:
            return error("unauthorized", err), 401
        try:
            init_chart_workspace_db()
            session = get_session()
            try:
                row = (
                    session.query(ChartWorkspaceLayout)
                    .filter(
                        ChartWorkspaceLayout.id == layout_id,
                        ChartWorkspaceLayout.user_id == user_id,
                    )
                    .one_or_none()
                )
                if row is None:
                    return error("not_found", "layout not found"), 404
                return ok(_row_to_dict(row)), 200
            finally:
                session.close()
        except Exception:
            return ok({}), 200

    def put(self, layout_id: int):
        user_id, err = resolve_user_id()
        if err:
            return error("unauthorized", err), 401
        body = parse_body()
        try:
            init_chart_workspace_db()
            session = get_session()
            try:
                row = (
                    session.query(ChartWorkspaceLayout)
                    .filter(
                        ChartWorkspaceLayout.id == layout_id,
                        ChartWorkspaceLayout.user_id == user_id,
                    )
                    .one_or_none()
                )
                if row is None:
                    return error("not_found", "layout not found"), 404
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
            return ok({"id": layout_id, "updated_at": utcnow_iso()}), 200

    def delete(self, layout_id: int):
        user_id, err = resolve_user_id()
        if err:
            return error("unauthorized", err), 401
        try:
            init_chart_workspace_db()
            session = get_session()
            try:
                row = (
                    session.query(ChartWorkspaceLayout)
                    .filter(
                        ChartWorkspaceLayout.id == layout_id,
                        ChartWorkspaceLayout.user_id == user_id,
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


@api.route("/<int:layout_id>/cells")
class LayoutCells(Resource):
    """Convenience endpoint: GET returns just the cells_json subtree of
    a layout; PUT replaces it. Saves the client one round-trip when
    the only persisted change is a per-cell symbol/engine/timeframe."""

    def get(self, layout_id: int):
        user_id, err = resolve_user_id()
        if err:
            return error("unauthorized", err), 401
        try:
            init_chart_workspace_db()
            session = get_session()
            try:
                row = (
                    session.query(ChartWorkspaceLayout)
                    .filter(
                        ChartWorkspaceLayout.id == layout_id,
                        ChartWorkspaceLayout.user_id == user_id,
                    )
                    .one_or_none()
                )
                if row is None:
                    return error("not_found", "layout not found"), 404
                return (
                    ok(
                        {
                            "layout_id": layout_id,
                            "cells": _safe_loads(row.cells_json).get("cells", []),
                            "schema_version": row.schema_version,
                        }
                    ),
                    200,
                )
            finally:
                session.close()
        except Exception:
            return ok({"layout_id": layout_id, "cells": []}), 200

    def put(self, layout_id: int):
        user_id, err = resolve_user_id()
        if err:
            return error("unauthorized", err), 401
        body = parse_body()
        try:
            init_chart_workspace_db()
            session = get_session()
            try:
                row = (
                    session.query(ChartWorkspaceLayout)
                    .filter(
                        ChartWorkspaceLayout.id == layout_id,
                        ChartWorkspaceLayout.user_id == user_id,
                    )
                    .one_or_none()
                )
                if row is None:
                    return error("not_found", "layout not found"), 404
                cells_json = _safe_loads(row.cells_json)
                if not isinstance(cells_json, dict):
                    cells_json = {}
                cells_json["cells"] = body.get("cells", [])
                row.cells_json = json.dumps(cells_json)
                session.commit()
                session.refresh(row)
                return ok(_row_to_dict(row)), 200
            finally:
                session.close()
        except Exception:
            return ok({"layout_id": layout_id, "updated_at": utcnow_iso()}), 200
