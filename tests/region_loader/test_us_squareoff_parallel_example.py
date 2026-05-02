"""Phase 2 T-11 — US squareoff parallel example.

The US sandbox provider currently keeps ``_DAY_TRADE_CLOSE_HHMM = (16,
0)`` inline; Phase 2 ships a parallel example data table at
``market_regions/us/squareoff.py`` so the schema-validation tests can
confirm every region carries a ``mandatory_close_rules`` payload of
the same shape. Phase 7 owns the actual wiring of the US sandbox
engine to read from the table.

This is a thin shape-pinning test — the values themselves are owned by
the US plugin and may evolve as Phase 7 adds session-aware US
day-trade rules; the *shape* is what Phase 2 needs to keep stable.
"""

from __future__ import annotations

from market_regions.us.squareoff import MANDATORY_CLOSE_RULES


def test_us_squareoff_rules_are_a_list_of_dicts():
    assert isinstance(MANDATORY_CLOSE_RULES, list)
    assert MANDATORY_CLOSE_RULES, "US squareoff rules must not be empty"
    for rule in MANDATORY_CLOSE_RULES:
        assert isinstance(rule, dict)
        assert set(rule) >= {"venue", "local_close", "applies_to"}
        assert isinstance(rule["venue"], str)
        assert isinstance(rule["local_close"], str)
        assert isinstance(rule["applies_to"], list)


def test_us_squareoff_uses_us_venue_codes_not_india():
    venues = {rule["venue"] for rule in MANDATORY_CLOSE_RULES}
    assert venues, "US rule list must reference at least one US venue"
    # Sanity guard against a copy-paste mistake — US rules must NOT
    # carry NSE / BSE / NFO / BFO / CDS / BCD / MCX / NCDEX.
    forbidden = {"NSE", "BSE", "NFO", "BFO", "CDS", "BCD", "MCX", "NCDEX"}
    overlap = venues & forbidden
    assert not overlap, (
        f"US squareoff rules referenced India venues {sorted(overlap)!r}; "
        "this would violate ADR 0006 (no India literal in non-India "
        "region plugins)."
    )


def test_us_squareoff_uses_day_trade_product():
    """The US analog of MIS is ``DAY_TRADE``. Pinning the product code
    catches a regression where someone copy-pastes the India ``MIS``
    code into the US rules."""
    products: set[str] = set()
    for rule in MANDATORY_CLOSE_RULES:
        products.update(rule["applies_to"])
    assert "DAY_TRADE" in products
    assert "MIS" not in products
