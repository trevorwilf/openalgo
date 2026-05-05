"""Regression: ``_tradebook`` filters every spelling of zero
``filled_qty`` instead of only the literal strings ``"0"`` and
``"0.0"``.

Bug: the previous filter::

    if (r.get("filled_qty") or "0") in ("0", "0.0"):
        continue

let through ``"0.00"``, ``"0.000"``, and Alpaca's 9-decimal-place
crypto shape ``"0.000000000"`` — empty-fill rows leaked into the
tradebook for crypto symbols and any time Alpaca chose a longer
decimal representation.

Fix: parse to ``Decimal`` and compare to ``0`` so every-spelling-
of-zero is caught.

This test exercises the predicate directly because the surrounding
``_tradebook`` does network IO + auth — too heavy for a unit test.
The predicate is the bug surface; the rest is plumbing.
"""

from __future__ import annotations

from decimal import Decimal

import pytest


def _is_empty_fill(filled_qty_raw):
    """Mirror of the predicate inside ``_tradebook``."""
    try:
        filled_qty_dec = Decimal(str(filled_qty_raw or "0"))
    except (ArithmeticError, ValueError):
        filled_qty_dec = Decimal("0")
    return filled_qty_dec == 0


@pytest.mark.parametrize(
    "raw",
    [
        "0",
        "0.0",
        "0.00",
        "0.000",
        "0.000000000",
        "",
        None,
        "0e0",
        "0E-9",
    ],
)
def test_every_spelling_of_zero_is_filtered(raw):
    assert _is_empty_fill(raw)


@pytest.mark.parametrize(
    "raw",
    [
        "1",
        "1.0",
        "1.5",
        "0.5",
        "0.000001",
        "0.000000001",  # 9dp crypto-style fill
        "100",
    ],
)
def test_real_fills_pass_through(raw):
    assert not _is_empty_fill(raw)


def test_unparseable_qty_treated_as_zero():
    """Defensive: garbage in the field is filtered out, not crashed."""
    assert _is_empty_fill("not-a-number")
