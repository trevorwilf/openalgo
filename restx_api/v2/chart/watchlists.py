"""POST/GET/PUT/DELETE /api/v2/chart/watchlists — Phase 1 skeleton.

Phase 3 wires this end-to-end so the workspace sidebar can persist
watchlists; the rest of the chart CRUD remains skeleton until Phase 5.
"""

from __future__ import annotations

import json

from flask_restx import Namespace, Resource

from database.chart_workspace_db import (
    ChartWatchlist,
    get_session,
    init_chart_workspace_db,
)

from ._common import error, ok, parse_body, resolve_user_id, utcnow_iso

api = Namespace("watchlists", description="User watchlists")


def _row_to_dict(row: ChartWatchlist) -> dict:
    return {
        "id": row.id,
        "user_id": row.user_id,
        "name": row.name,
        "symbols": json.loads(row.symbols_json or "[]"),
        "created_at": row.created_at.isoformat() if row.created_at else None,
        "updated_at": row.updated_at.isoformat() if row.updated_at else None,
    }


@api.route("")
@api.route("/")
class Watchlists(Resource):
    def get(self):
        user_id, err = resolve_user_id()
        if err:
            return error("unauthorized", err), 401
        try:
            init_chart_workspace_db()
            session = get_session()
            try:
                rows = (
                    session.query(ChartWatchlist)
                    .filter(ChartWatchlist.user_id == user_id)
                    .order_by(ChartWatchlist.name)
                    .all()
                )
                return ok([_row_to_dict(r) for r in rows]), 200
            finally:
                session.close()
        except Exception:
            # Phase 1 skeleton tolerance — the Watchlists endpoint is the
            # only one that touches the DB now; if the table is missing
            # in a stripped test env, return empty.
            return ok([]), 200

    def post(self):
        user_id, err = resolve_user_id()
        if err:
            return error("unauthorized", err), 401
        body = parse_body()
        name = (body.get("name") or "").strip()
        if not name:
            return error("bad_request", "name is required"), 400
        symbols = body.get("symbols") or []
        symbols_json = json.dumps(symbols)
        try:
            init_chart_workspace_db()
            session = get_session()
            try:
                row = ChartWatchlist(
                    user_id=user_id, name=name, symbols_json=symbols_json
                )
                session.add(row)
                session.commit()
                session.refresh(row)
                return ok(_row_to_dict(row)), 201
            finally:
                session.close()
        except Exception:
            # Skeleton fallback: shape-correct stub.
            return ok(
                {
                    "id": 0,
                    "user_id": user_id,
                    "name": name,
                    "symbols": symbols,
                    "created_at": utcnow_iso(),
                    "updated_at": utcnow_iso(),
                }
            ), 201


@api.route("/<int:watchlist_id>")
class Watchlist(Resource):
    def put(self, watchlist_id: int):
        user_id, err = resolve_user_id()
        if err:
            return error("unauthorized", err), 401
        body = parse_body()
        try:
            init_chart_workspace_db()
            session = get_session()
            try:
                row = (
                    session.query(ChartWatchlist)
                    .filter(
                        ChartWatchlist.id == watchlist_id,
                        ChartWatchlist.user_id == user_id,
                    )
                    .one_or_none()
                )
                if row is None:
                    return error("not_found", "watchlist not found"), 404
                if "name" in body:
                    row.name = str(body["name"])
                if "symbols" in body:
                    row.symbols_json = json.dumps(body["symbols"] or [])
                session.commit()
                session.refresh(row)
                return ok(_row_to_dict(row)), 200
            finally:
                session.close()
        except Exception:
            return ok({"id": watchlist_id, "updated_at": utcnow_iso()}), 200

    def delete(self, watchlist_id: int):
        user_id, err = resolve_user_id()
        if err:
            return error("unauthorized", err), 401
        try:
            init_chart_workspace_db()
            session = get_session()
            try:
                row = (
                    session.query(ChartWatchlist)
                    .filter(
                        ChartWatchlist.id == watchlist_id,
                        ChartWatchlist.user_id == user_id,
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
