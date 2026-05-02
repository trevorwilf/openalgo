"""Phase 2 T-15 — byte-identical relocation of India locale helpers.

``format_indian_currency`` and ``format_indian_number`` were inline in
``utils/number_formatter.py`` before the refactor. Phase 2 T-15
relocates the implementation to ``market_regions/india/locale.py`` and
keeps the legacy import paths working via re-export. This test pins
the formatter behavior so any future drift fails loudly.
"""

from __future__ import annotations

import pytest

from market_regions.india.locale import (
    INDIAN_CURRENCY_LOCALE,
    format_indian_currency,
    format_indian_number,
)


def test_locale_constants():
    assert INDIAN_CURRENCY_LOCALE["currency"] == "INR"
    assert INDIAN_CURRENCY_LOCALE["symbol"] == "₹"  # ₹
    assert INDIAN_CURRENCY_LOCALE["locale"] == "en-IN"
    assert INDIAN_CURRENCY_LOCALE["lakh_threshold"] == 100000
    assert INDIAN_CURRENCY_LOCALE["crore_threshold"] == 10000000


@pytest.mark.parametrize(
    "value, expected",
    [
        (10000000.0, "1.00Cr"),
        (9978000.0, "99.78L"),
        (10000.0, "10000.00"),
        (-5000000.0, "-50.00L"),
        (-10000000.0, "-1.00Cr"),
        (99.5, "99.50"),
        (0, "0.00"),
        ("not a number", "not a number"),
    ],
)
def test_format_indian_number(value, expected):
    assert format_indian_number(value) == expected


def test_format_indian_currency_prefixes_rupee_sign():
    assert format_indian_currency(10000000.0) == "₹1.00Cr"
    assert format_indian_currency(9978000.0) == "₹99.78L"
    assert format_indian_currency(0) == "₹0.00"


def test_legacy_import_path_is_a_reexport():
    """The legacy import path
    ``utils.number_formatter.format_indian_currency`` must continue to
    work, and it must be the *same callable* as the relocated one — a
    re-export, not a divergent copy."""
    from utils.number_formatter import format_indian_currency as legacy_fc
    from utils.number_formatter import format_indian_number as legacy_fn

    assert legacy_fc is format_indian_currency
    assert legacy_fn is format_indian_number
