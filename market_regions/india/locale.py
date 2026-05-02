"""India locale-aware number / currency formatters — Phase 2 T-15 relocation.

Source of truth for the legacy India number-formatting helpers
(``format_indian_number`` produces ``"1.00Cr"`` / ``"99.78L"``;
``format_indian_currency`` adds the ``₹`` prefix). Relocated
byte-equivalently from ``utils/number_formatter.py``; that module now
re-exports the symbols so the existing legacy India callers continue
to import them from the same path.

Promoted-lane code uses ``utils.number_formatter.format_currency_amount``
instead — that helper takes an explicit currency and locale and never
infers India.
"""

from __future__ import annotations

from typing import Any


# Per ADR 0006 the literal-scanner allowlist already covers the ``₹``
# symbol on this module path because it's a region-plugin file.
INDIAN_CURRENCY_LOCALE: dict[str, Any] = {
    "currency": "INR",
    "symbol": "₹",
    "locale": "en-IN",
    "lakh_threshold": 100000,
    "crore_threshold": 10000000,
}


def format_indian_number(value: Any) -> str:
    """Format number in Indian format with Cr/L suffixes.

    Examples::

        10000000.0 -> "1.00Cr"
        9978000.0  -> "99.78L"
        10000.0    -> "10000.00"
        -5000000.0 -> "-50.00L"
    """
    try:
        num = float(value)
        is_negative = num < 0
        num = abs(num)
        if num >= 10000000:
            formatted = f"{num / 10000000:.2f}Cr"
        elif num >= 100000:
            formatted = f"{num / 100000:.2f}L"
        else:
            formatted = f"{num:.2f}"
        if is_negative:
            formatted = f"-{formatted}"
        return formatted
    except (ValueError, TypeError):
        return str(value)


def format_indian_currency(value: Any) -> str:
    """Format number as Indian currency (₹)."""
    return f"₹{format_indian_number(value)}"


__all__ = [
    "INDIAN_CURRENCY_LOCALE",
    "format_indian_currency",
    "format_indian_number",
]
