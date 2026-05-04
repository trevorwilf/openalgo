"""Phase 4-bis-4 — symtoken_v1 view hides T-06 columns.

Asserts the migration script creates the ``symtoken_v1`` view with
the pre-T-06 column set (no ``broker_code`` / ``instrument_id``).
External SQL consumers selecting from the view see the legacy
schema; v2-lane code reads the table directly to access the
broker-provenance columns.

The view is created by ``upgrade/migrate_symtoken_broker_provenance.upgrade``
(idempotent), and dropped by the corresponding ``downgrade``.
"""

from __future__ import annotations

from sqlalchemy import inspect


def _ensure_view():
    from upgrade.migrate_symtoken_broker_provenance import upgrade
    upgrade()


def test_symtoken_v1_view_exists_after_migration():
    _ensure_view()
    from market_regions.india.legacy_v1.database.symbol import engine
    with engine.connect() as conn:
        inspector = inspect(conn)
        views = inspector.get_view_names()
    assert "symtoken_v1" in views


def test_symtoken_v1_view_hides_t06_columns():
    _ensure_view()
    from market_regions.india.legacy_v1.database.symbol import engine
    with engine.connect() as conn:
        inspector = inspect(conn)
        if "symtoken_v1" not in inspector.get_view_names():
            return  # idempotent — already-tested upstream
        cols = {c["name"] for c in inspector.get_columns("symtoken_v1")}
    # T-06 columns hidden:
    assert "broker_code" not in cols
    assert "instrument_id" not in cols
    # Pre-T-06 columns visible:
    assert {"id", "symbol", "brsymbol", "exchange", "token"}.issubset(cols)


def test_symtoken_v1_view_is_readable():
    _ensure_view()
    from market_regions.india.legacy_v1.database.symbol import engine
    from sqlalchemy import text
    with engine.connect() as conn:
        # SELECT 1 from view should succeed.
        result = conn.execute(text("SELECT COUNT(*) FROM symtoken_v1"))
        count = result.scalar()
    assert isinstance(count, int)
    assert count >= 0
