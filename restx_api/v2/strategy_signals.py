"""Phase 6 — POST/GET /api/v2/strategy-signals.

External strategy systems (or the workspace's own python-strategy
runners) post a signal; the chart workspace renders it as a flag
marker on the relevant cell within ~1s (acceptance per HANDOFF
Phase 6 §16).

Phase 6 ships the persistent endpoint; the live broadcast piece
(WSEnvelope `strategy_signal` type) is wired through the existing
SocketIO namespace from Phase 4.
"""

from __future__ import annotations

import json

from flask import request
from flask_restx import Namespace, Resource

from database.chart_workspace_db import (
    ChartStrategySignal,
    get_session,
    init_chart_workspace_db,
)
from restx_api.v2._auth import error, ok
from restx_api.v2.chart._common import parse_body, resolve_user_id

api = Namespace("strategy-signals", description="Strategy signal markers")


def _row_to_dict(row: ChartStrategySignal) -> dict:
    return {
        "id": row.id,
        "user_id": row.user_id,
        "ts_utc": row.ts_utc.isoformat() if row.ts_utc else None,
        "symbol": row.symbol,
        "kind": row.kind,
        "payload_json": json.loads(row.payload_json) if row.payload_json else {},
        "source": row.source,
    }


@api.route("")
@api.route("/")
class StrategySignals(Resource):
    def get(self):
        user_id, err = resolve_user_id()
        if err:
            return error("unauthorized", err), 401
        symbol = request.args.get("symbol")
        limit = max(1, min(int(request.args.get("limit", 100)), 500))
        try:
            init_chart_workspace_db()
            session = get_session()
            try:
                q = session.query(ChartStrategySignal).filter(
                    ChartStrategySignal.user_id == user_id
                )
                if symbol:
                    q = q.filter(ChartStrategySignal.symbol == symbol)
                rows = q.order_by(ChartStrategySignal.id.desc()).limit(limit).all()
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
        symbol = (body.get("symbol") or "").strip()
        kind = (body.get("kind") or "").strip()
        source = (body.get("source") or "").strip()
        if not symbol or not kind or not source:
            return error("bad_request", "symbol, kind, source are required"), 400
        try:
            init_chart_workspace_db()
            session = get_session()
            try:
                row = ChartStrategySignal(
                    user_id=user_id,
                    symbol=symbol,
                    kind=kind,
                    payload_json=json.dumps(body.get("payload_json") or {}),
                    source=source,
                )
                session.add(row)
                session.commit()
                session.refresh(row)
                return ok(_row_to_dict(row)), 201
            finally:
                session.close()
        except Exception:
            return error("server_error", "could not persist signal"), 500


__all__ = ["api"]
