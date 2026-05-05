"""Phase 6 — append-only audit logger for chart-originated intents.

Every chart-originated order intent (placed, cancelled-before-confirm,
rejected-by-validator, rejected-by-broker, executed) writes a row to
``audit_log_chart_orders``. The DB-level trigger blocks DELETE so
rows are forever (Q-17).

Phase 6 emits via the synchronous SQLAlchemy session; the publisher
side (display tree + execution tree) calls
:func:`record_audit_event` with the intent metadata.
"""

from __future__ import annotations

import json
from typing import Any, Literal

from database.chart_workspace_db import (
    AuditLogChartOrder,
    get_session,
    init_chart_workspace_db,
)
from utils.logging import get_logger

logger = get_logger(__name__)

AuditStatus = Literal[
    "PLACED",
    "CANCELLED_PRE_CONFIRM",
    "REJECTED_VALIDATOR",
    "REJECTED_BROKER",
    "EXECUTED",
]


def record_audit_event(
    *,
    user_id: str,
    account_id: str,
    intent_kind: Literal["place", "modify", "cancel"],
    symbol: str,
    qty: str | int | float,
    price: str | int | float | None,
    idempotency_token: str,
    status: AuditStatus,
    broker_response: dict[str, Any] | None = None,
) -> int | None:
    """Append a chart-orders audit row. Returns the row id on success
    or None on DB unavailability (rare; best-effort logging path).
    """
    try:
        init_chart_workspace_db()
        session = get_session()
        try:
            row = AuditLogChartOrder(
                user_id=user_id,
                account_id=account_id,
                intent_kind=intent_kind,
                symbol=symbol,
                qty=str(qty),
                price=None if price is None else str(price),
                idempotency_token=idempotency_token,
                status=status,
                broker_response_json=(
                    json.dumps(broker_response) if broker_response is not None else None
                ),
                chart_origin=True,
            )
            session.add(row)
            session.commit()
            session.refresh(row)
            return row.id
        finally:
            session.close()
    except Exception:  # noqa: BLE001
        logger.exception("audit row write failed for token=%s", idempotency_token)
        return None


__all__ = ["AuditStatus", "record_audit_event"]
