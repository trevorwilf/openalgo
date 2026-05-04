"""T-15 (v7 Phase 4-bis) — historify market_data has broker_code.

Asserts the historify market_data table declares a ``broker_code``
column. Operators with pre-Phase-4-bis databases pick up the
column via the ``ALTER TABLE ADD COLUMN IF NOT EXISTS`` upgrade in
``init_database()``.

The composite unique constraint
``(broker_code, symbol, exchange, interval, timestamp)`` and the
backfill migration are deferred to a Phase 4-bis-2 follow-up
alongside operator coordination.
"""

from __future__ import annotations


def test_historify_market_data_has_broker_code_column():
    """Inspect the live historify schema after init_database()."""
    from market_regions.india.legacy_v1.database import historify_db

    historify_db.init_database()
    with historify_db.get_connection() as conn:
        cols = conn.execute(
            "SELECT column_name FROM information_schema.columns "
            "WHERE table_name = 'market_data'"
        ).fetchall()
    column_names = {row[0] for row in cols}
    assert "broker_code" in column_names, (
        "T-15: historify market_data.broker_code column missing"
    )
    # The pre-existing instrument_id column is also retained so
    # the cross-broker pair is consistent with SymToken (T-06).
    assert "instrument_id" in column_names
