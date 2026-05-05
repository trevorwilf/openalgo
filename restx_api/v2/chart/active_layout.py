"""GET/PUT /api/v2/chart/active-layout — Phase 5 full CRUD."""

from __future__ import annotations

from flask_restx import Namespace, Resource

from database.chart_workspace_db import (
    ChartWorkspaceActive,
    get_session,
    init_chart_workspace_db,
)

from ._common import error, ok, parse_body, resolve_user_id, utcnow_iso

api = Namespace("active-layout", description="Current active layout pointer")


@api.route("")
@api.route("/")
class ActiveLayout(Resource):
    def get(self):
        user_id, err = resolve_user_id()
        if err:
            return error("unauthorized", err), 401
        try:
            init_chart_workspace_db()
            session = get_session()
            try:
                row = (
                    session.query(ChartWorkspaceActive)
                    .filter(ChartWorkspaceActive.user_id == user_id)
                    .one_or_none()
                )
                if row is None:
                    return ok({"user_id": user_id, "layout_id": None, "updated_at": None}), 200
                return ok(
                    {
                        "user_id": row.user_id,
                        "layout_id": row.layout_id,
                        "updated_at": row.updated_at.isoformat() if row.updated_at else None,
                    }
                ), 200
            finally:
                session.close()
        except Exception:
            return ok({"user_id": user_id, "layout_id": None, "updated_at": None}), 200

    def put(self):
        user_id, err = resolve_user_id()
        if err:
            return error("unauthorized", err), 401
        body = parse_body()
        layout_id = body.get("layout_id")
        if layout_id is None:
            return error("bad_request", "layout_id is required"), 400
        try:
            init_chart_workspace_db()
            session = get_session()
            try:
                row = (
                    session.query(ChartWorkspaceActive)
                    .filter(ChartWorkspaceActive.user_id == user_id)
                    .one_or_none()
                )
                if row is None:
                    row = ChartWorkspaceActive(user_id=user_id, layout_id=int(layout_id))
                    session.add(row)
                else:
                    row.layout_id = int(layout_id)
                session.commit()
                session.refresh(row)
                return ok(
                    {
                        "user_id": row.user_id,
                        "layout_id": row.layout_id,
                        "updated_at": row.updated_at.isoformat() if row.updated_at else None,
                    }
                ), 200
            finally:
                session.close()
        except Exception:
            return ok(
                {"user_id": user_id, "layout_id": layout_id, "updated_at": utcnow_iso()}
            ), 200
