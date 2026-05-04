"""T-06 (v7 Phase 4-bis) — SymToken broker provenance columns.

Asserts the model declares ``broker_code`` and ``instrument_id``
columns + the cross-broker index. The unique constraint
``(broker_code, symbol, exchange)`` and the v1-lane DB view land
in a follow-up commit alongside operator coordination — this test
locks the additive schema change.
"""

from __future__ import annotations


def test_symtoken_has_broker_code_column():
    from market_regions.india.legacy_v1.database.symbol import SymToken

    columns = {col.name for col in SymToken.__table__.columns}
    assert "broker_code" in columns
    # nullable initially so existing rows survive without migration.
    col = SymToken.__table__.columns["broker_code"]
    assert col.nullable is True


def test_symtoken_has_instrument_id_column():
    from market_regions.india.legacy_v1.database.symbol import SymToken

    columns = {col.name for col in SymToken.__table__.columns}
    assert "instrument_id" in columns


def test_symtoken_has_cross_broker_index():
    from market_regions.india.legacy_v1.database.symbol import SymToken

    indexes = {idx.name for idx in SymToken.__table__.indexes}
    assert "idx_broker_symbol_exchange" in indexes


def test_legacy_indices_preserved():
    """The pre-T-06 indices remain so existing query plans don't
    regress."""
    from market_regions.india.legacy_v1.database.symbol import SymToken

    indexes = {idx.name for idx in SymToken.__table__.indexes}
    assert "idx_symbol_exchange" in indexes
    assert "idx_symbol_name" in indexes
    assert "idx_brsymbol_exchange" in indexes


def test_migration_script_resolves_active_broker():
    """The migration script's broker resolver returns a string
    without raising. Returns "" when no DEFAULT_BROKER env is set."""
    import os

    prev = os.environ.pop("DEFAULT_BROKER", None)
    try:
        from upgrade.migrate_symtoken_broker_provenance import _resolve_active_broker

        result = _resolve_active_broker()
        assert isinstance(result, str)
    finally:
        if prev is not None:
            os.environ["DEFAULT_BROKER"] = prev


def test_migration_script_honors_default_broker_env(monkeypatch):
    monkeypatch.setenv("DEFAULT_BROKER", "zerodha")
    from upgrade.migrate_symtoken_broker_provenance import _resolve_active_broker

    assert _resolve_active_broker() == "zerodha"
