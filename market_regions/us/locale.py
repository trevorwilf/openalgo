"""US locale-aware number / currency formatters — Phase 7b T-30
build-out.

USD currency with standard thousands grouping
(``$1,234.56`` / ``-$1,234.56``). Two decimal places by convention.
Promoted-lane code uses ``utils.number_formatter.format_currency_amount``;
this module exposes a USD-specific helper for explicit US-flow code
that wants the canonical formatter without going through the
currency-aware lookup.
"""

from __future__ import annotations

from decimal import Decimal, InvalidOperation
from typing import Any


US_CURRENCY_LOCALE: dict[str, Any] = {
    "currency": "USD",
    "symbol": "$",
    "locale": "en-US",
    "decimal_places": 2,
}


def format_us_currency(value: Any) -> str:
    """Format ``value`` as ``$1,234.56`` / ``-$1,234.56``.

    Returns ``str(value)`` for unparseable inputs (mirroring the
    legacy India helper's defensive contract). Negative values render
    with a leading ``-`` before the symbol.
    """
    try:
        amount = Decimal(str(value))
    except (ValueError, TypeError, InvalidOperation):
        return str(value)
    is_negative = amount < 0
    abs_amount = abs(amount)
    rounded = abs_amount.quantize(Decimal("0.01"))
    body = f"${rounded:,.2f}"
    return f"-{body}" if is_negative else body


__all__ = ["US_CURRENCY_LOCALE", "format_us_currency"]
