"""v7 Phase 4-bis-6 — SymTokenV1Read ORM model.

Asserts the read-only ORM model that maps over the
``symtoken_v1`` view exists, exposes only the pre-T-06 column
set, and is importable from the same module as ``SymToken``.

The view itself is created by
``upgrade/migrate_symtoken_broker_provenance.upgrade``; this
test pins the model contract so v1-lane callers can confidently
opt into it.
"""

from __future__ import annotations


def test_symtokenv1read_importable():
    from market_regions.india.legacy_v1.database.symbol import SymTokenV1Read

    assert SymTokenV1Read is not None
    assert SymTokenV1Read.__tablename__ == "symtoken_v1"


def test_symtokenv1read_excludes_broker_code():
    from market_regions.india.legacy_v1.database.symbol import SymTokenV1Read

    cols = {c.name for c in SymTokenV1Read.__table__.columns}
    assert "broker_code" not in cols
    assert "instrument_id" not in cols


def test_symtokenv1read_includes_legacy_columns():
    from market_regions.india.legacy_v1.database.symbol import SymTokenV1Read

    cols = {c.name for c in SymTokenV1Read.__table__.columns}
    legacy = {
        "id", "symbol", "brsymbol", "name", "exchange", "brexchange",
        "token", "expiry", "strike", "lotsize", "instrumenttype",
        "tick_size", "contract_value",
    }
    assert legacy.issubset(cols)


def test_symtokenv1read_marked_as_view():
    """The model declares ``info={"is_view": True}`` so SQLAlchemy
    skips it during ``create_all()`` (the view is created by the
    migration script, not the ORM)."""
    from market_regions.india.legacy_v1.database.symbol import SymTokenV1Read

    info = SymTokenV1Read.__table__.info
    assert info.get("is_view") is True


def test_symtokenv1read_separate_from_symtoken():
    """``SymToken`` and ``SymTokenV1Read`` are distinct ORM
    classes mapping different SQL entities (table vs. view)."""
    from market_regions.india.legacy_v1.database.symbol import (
        SymToken,
        SymTokenV1Read,
    )

    assert SymToken is not SymTokenV1Read
    assert SymToken.__tablename__ == "symtoken"
    assert SymTokenV1Read.__tablename__ == "symtoken_v1"
