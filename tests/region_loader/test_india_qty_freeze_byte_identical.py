"""Phase 2 T-12 — byte-identical relocation of NFO qty-freeze rules.

The quantity-freeze table for Indian F&O positions is stored as a
runtime CSV cache in ``database/qty_freeze_db.py``; the
*regulatory shape* (NFO has a per-underlying CSV; other India venues
default to 1) is the part Phase 2 T-12 captures in
``market_regions/india/qty_freeze.py``. This test pins the relocated
shape.
"""

from __future__ import annotations

from market_regions.india.qty_freeze import QUANTITY_FREEZE_RULES


def test_only_nfo_has_an_explicit_freeze_rule():
    """Phase 2 T-12 only carries the NFO row; BFO/CDS/MCX continue to
    fall through the default-1 path in
    ``database.qty_freeze_db.get_freeze_qty``. Adding rows here would
    imply we want region-plugin-driven defaults for those venues —
    that's a separate decision and a different commit."""
    assert len(QUANTITY_FREEZE_RULES) == 1
    rule = QUANTITY_FREEZE_RULES[0]
    assert rule["venue"] == "NFO"
    assert rule["underlying_pattern"] is None
    assert rule["qty_freeze"] is None
    assert rule["default_qty_freeze"] == 1
    assert rule["csv_source"] == "data/qtyfreeze.csv"


def test_legacy_qty_freeze_db_still_uses_csv_path_for_nfo():
    """Make sure the legacy qty_freeze_db loader still reads from the
    CSV path declared in the relocated rule — drift would mean we have
    two sources of truth disagreeing on where the data lives."""
    import inspect

    from database import qty_freeze_db

    src = inspect.getsource(qty_freeze_db.ensure_qty_freeze_tables_exists)
    assert "qtyfreeze.csv" in src, (
        "qty_freeze_db.ensure_qty_freeze_tables_exists dropped the "
        "CSV reference; it must keep loading from "
        "data/qtyfreeze.csv to match the relocated rule."
    )
