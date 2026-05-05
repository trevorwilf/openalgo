"""Phase 6 — GET /api/v2/audit/chart-orders.

Append-only read API. Every chart-originated intent writes here and
DELETE is blocked at the DB level (Q-17 trigger from Phase 1
migration). The endpoint returns the most-recent N rows with
optional filters.
"""

from __future__ import annotations

import json

from flask import request
from flask_restx import Namespace, Resource

from database.chart_workspace_db import (
    AuditLogChartOrder,
    get_session,
    init_chart_workspace_db,
)
from restx_api.v2._auth import error, ok
from restx_api.v2.chart._common import resolve_user_id

api = Namespace("audit-chart-orders", description="Chart-originated order audit log")


def _row_to_dict(row: AuditLogChartOrder) -> dict:
    return {
        "id": row.id,
        "user_id": row.user_id,
        "account_id": row.account_id,
        "ts_utc": row.ts_utc.isoformat() if row.ts_utc else None,
        "intent_kind": row.intent_kind,
        "symbol": row.symbol,
        "qty": row.qty,
        "price": row.price,
        "idempotency_token": row.idempotency_token,
        "status": row.status,
        "broker_response_json": (
            json.loads(row.broker_response_json) if row.broker_response_json else None
        ),
        "chart_origin": bool(row.chart_origin),
    }


@api.route("")
@api.route("/")
class AuditChartOrders(Resource):
    def get(self):
        user_id, err = resolve_user_id()
        if err:
            return error("unauthorized", err), 401
        limit = max(1, min(int(request.args.get("limit", 100)), 500))
        try:
            init_chart_workspace_db()
            session = get_session()
            try:
                rows = (
                    session.query(AuditLogChartOrder)
                    .filter(AuditLogChartOrder.user_id == user_id)
                    .order_by(AuditLogChartOrder.id.desc())
                    .limit(limit)
                    .all()
                )
                return ok([_row_to_dict(r) for r in rows]), 200
            finally:
                session.close()
        except Exception:
            return ok([]), 200

    def delete(self):
        # The DB trigger raises on DELETE. We also explicitly refuse the
        # HTTP method so a curl rm doesn't even reach the trigger — the
        # 405 + audit_immutable code is the contract surface tested by
        # tests/api_v2/charts/test_audit_chart_orders.py.
        return error("audit_immutable", "audit_log_chart_orders is append-only"), 405


__all__ = ["api"]
