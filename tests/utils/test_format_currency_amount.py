"""Phase 6 v4 (ADR 0023) — format_currency_amount unit tests.

The promoted-lane currency formatter takes an explicit currency code
from the calling component (which derives it from the active broker's
default_currency capability or the position/order's currency). Never
infers India.
"""

from __future__ import annotations

from decimal import Decimal

from utils.number_formatter import format_currency_amount


def test_usd_basic():
    assert format_currency_amount("1234.56", "USD") == "$1,234.56"


def test_eur_basic():
    assert format_currency_amount("999.99", "EUR") == "€999.99"


def test_gbp_basic():
    assert format_currency_amount("100", "GBP") == "£100.00"


def test_inr_basic():
    """INR is supported but the formatter does NOT use Indian numbering
    grouping — that's the legacy India helper's job. Promoted code
    that wants India-style grouping must call format_indian_currency
    explicitly."""
    assert format_currency_amount("100000", "INR") == "₹100,000.00"


def test_jpy_zero_decimals():
    assert format_currency_amount("12345", "JPY") == "¥12,345"


def test_btc_eight_decimals():
    assert format_currency_amount("0.00123456", "BTC") == "₿0.00123456"


def test_negative_value():
    assert format_currency_amount("-1234.56", "USD") == "-$1,234.56"


def test_unknown_currency_uses_code_prefix():
    assert format_currency_amount("100", "XYZ") == "XYZ 100.00"


def test_show_symbol_false_strips_symbol():
    assert format_currency_amount("1234.56", "USD", show_symbol=False) == "1,234.56"


def test_decimal_input_precise():
    assert format_currency_amount(Decimal("9999.999"), "USD") == "$10,000.00"


def test_empty_currency_renders_bare_number():
    assert format_currency_amount("100.00", "") == "100.00"


def test_invalid_amount_returns_string():
    assert format_currency_amount("not-a-number", "USD") == "not-a-number"


def test_thousands_grouping_is_standard_not_indian():
    """Promoted contract: grouping is 1,234,567 (US) not 12,34,567 (Indian)."""
    out = format_currency_amount("1234567.89", "USD")
    assert out == "$1,234,567.89"


def test_usdt_uses_code_prefix_with_space():
    assert format_currency_amount("500", "USDT") == "USDT 500.00"
