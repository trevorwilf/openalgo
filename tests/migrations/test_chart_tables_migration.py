"""Phase 1 — chart_workspace_db migration applies cleanly + DELETE block.

* All 9 chart tables are created.
* The DELETE-block trigger raises on attempts to delete from
  ``audit_log_chart_orders`` (Q-17).
* Migration is reversible: drop_all_for_test removes everything and a
  subsequent re-create works.
"""

from __future__ import annotations

import pytest
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.exc import IntegrityError, OperationalError
from sqlalchemy.pool import StaticPool


@pytest.fixture
def engine():
    """In-memory SQLite using StaticPool so the trigger persists across
    connections inside a single test (in-memory DB is per-connection).
    """
    return create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )


def test_create_all_creates_nine_chart_tables(engine):
    from database.chart_workspace_db import create_all_for_test

    create_all_for_test(engine)
    insp = inspect(engine)
    names = set(insp.get_table_names())
    expected = {
        "chart_workspace_layouts",
        "chart_drawings",
        "chart_indicators",
        "chart_watchlists",
        "chart_templates",
        "chart_workspace_active",
        "audit_log_chart_orders",
        "chart_strategy_signals",
        "chart_safety_settings",
    }
    assert expected.issubset(names)


def test_audit_delete_blocked_by_trigger(engine):
    from database.chart_workspace_db import (
        AuditLogChartOrder,
        create_all_for_test,
        get_engine,
    )
    import database.chart_workspace_db as cwdb

    create_all_for_test(engine)
    # Insert directly via raw SQL so we don't need the scoped session.
    with engine.begin() as conn:
        conn.execute(
            text(
                """
                INSERT INTO audit_log_chart_orders
                  (user_id, account_id, ts_utc, intent_kind, symbol, qty,
                   price, idempotency_token, status, broker_response_json,
                   chart_origin)
                VALUES
                  ('u1', 'acct1', :ts, 'place', 'AAPL', '1', '100',
                   'idem-1', 'ACK', NULL, 1)
                """
            ),
            {"ts": "2024-01-01 00:00:00"},
        )
    # Attempting DELETE must raise.
    with pytest.raises((IntegrityError, OperationalError)) as excinfo:
        with engine.begin() as conn:
            conn.execute(text("DELETE FROM audit_log_chart_orders WHERE id = 1"))
    msg = str(excinfo.value)
    assert "audit_log_chart_orders" in msg or "Q-17" in msg or "append-only" in msg


def test_drop_all_then_recreate_is_idempotent(engine):
    from database.chart_workspace_db import create_all_for_test, drop_all_for_test

    create_all_for_test(engine)
    drop_all_for_test(engine)
    insp = inspect(engine)
    assert "audit_log_chart_orders" not in insp.get_table_names()
    # Recreate should work.
    create_all_for_test(engine)
    insp = inspect(engine)
    assert "audit_log_chart_orders" in insp.get_table_names()


def test_layout_unique_constraint_user_name(engine):
    from database.chart_workspace_db import (
        ChartWorkspaceLayout,
        create_all_for_test,
    )
    from sqlalchemy.orm import Session

    create_all_for_test(engine)
    with Session(engine) as session:
        session.add(
            ChartWorkspaceLayout(
                user_id="u1", name="default", schema_version=1, cells_json="{}"
            )
        )
        session.commit()
        with pytest.raises(IntegrityError):
            session.add(
                ChartWorkspaceLayout(
                    user_id="u1", name="default", schema_version=1, cells_json="{}"
                )
            )
            session.commit()


def test_legacy_chart_preferences_not_touched(engine):
    """The new migration must NOT define a `chart_preferences` table —
    it lives behind the legacy India shim and is owned by the v1 lane.
    """
    from database.chart_workspace_db import Base

    new_tables = set(Base.metadata.tables.keys())
    assert "chart_preferences" not in new_tables
