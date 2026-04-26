"""Number formatting utilities.

* :func:`format_indian_number` and :func:`format_indian_currency` are
  the legacy India-shaped helpers (Cr / L suffix, ₹ prefix). They
  remain available for the legacy India lane and are NOT to be called
  from promoted code. The classifier marks this module as
  ``LEGACY_INDIA``; the literal scanner allowlists the few India
  characters here.

* :func:`format_currency_amount` is the v4 promoted-lane formatter
  (Phase 6 v4, ADR 0023). Takes an explicit currency code and locale,
  uses :class:`decimal.Decimal` precision, and never infers India.
  Promoted code uses this exclusively.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Any

LEGACY_INDIA_COMPATIBILITY = True


# ---------------------------------------------------------------------------
# Legacy India helpers — kept for the legacy India lane.
# ---------------------------------------------------------------------------


def format_indian_number(value: Any) -> str:
    """Format number in Indian format with Cr/L suffixes.

    Examples::

        10000000.0 -> "1.00Cr"
        9978000.0  -> "99.78L"
        10000.0    -> "10000.00"
        -5000000.0 -> "-50.00L"

    Legacy India helper. Promoted code uses
    :func:`format_currency_amount` instead.
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
    """Format number as Indian currency (₹). Legacy India helper."""
    return f"₹{format_indian_number(value)}"


# ---------------------------------------------------------------------------
# v4 promoted-lane formatter — currency-aware, locale-aware.
# ---------------------------------------------------------------------------


# Currency code -> (symbol, decimals, separator-style). 'in' uses the
# Indian numbering system (lakhs/crores grouping) when invoked in the
# India lane; promoted code passes a plain locale and gets standard
# thousands grouping.
_CURRENCY_META: dict[str, tuple[str, int]] = {
    "USD": ("$", 2),
    "EUR": ("€", 2),
    "GBP": ("£", 2),
    "JPY": ("¥", 0),
    "INR": ("₹", 2),
    "CHF": ("CHF", 2),
    "SGD": ("S$", 2),
    "HKD": ("HK$", 2),
    "AUD": ("A$", 2),
    "USDT": ("USDT", 2),
    "USDC": ("USDC", 2),
    "BTC": ("₿", 8),
    "ETH": ("Ξ", 6),
}


def format_currency_amount(
    amount: Decimal | float | int | str,
    currency: str,
    *,
    locale: str | None = None,
    show_symbol: bool = True,
) -> str:
    """Format ``amount`` as a currency string.

    Phase 6 v4 (ADR 0023) — the promoted-lane currency formatter.
    Takes the currency code from the calling component (which itself
    derives it from the active broker's ``default_currency`` capability
    or the position/order's currency for multi-currency accounts).

    Behavior:
        * Look up the symbol and decimal precision from
          :data:`_CURRENCY_META`. Unknown currencies fall through to
          the code itself as the prefix and 2 decimals.
        * Standard thousands-separator grouping (1,234,567.89) — no
          India-specific grouping (which is the legacy India helper's
          job).
        * Negative values rendered with a leading ``-`` *before* the
          symbol: ``-$1,234.56`` not ``$-1,234.56``.

    The ``locale`` parameter is reserved for a future Babel-backed
    full localization (digit grouping, decimal separator). Today it is
    accepted for forward compatibility and ignored.
    """
    from decimal import InvalidOperation

    try:
        decimal_amount = Decimal(str(amount))
    except (ValueError, TypeError, InvalidOperation):
        return str(amount)

    code = (currency or "").strip().upper()
    if not code:
        # Promoted contract: caller MUST pass a currency. We do not
        # silently default to INR. Render the bare number.
        return f"{decimal_amount:,.2f}"

    symbol, decimals = _CURRENCY_META.get(code, (code, 2))
    is_negative = decimal_amount < 0
    abs_amount = abs(decimal_amount)
    quant = Decimal(10) ** -decimals
    rounded = abs_amount.quantize(quant)
    formatted = f"{rounded:,.{decimals}f}"

    if not show_symbol:
        body = formatted
    elif symbol == code:
        # Code-style prefix (e.g., "USDT 1,234.56") — keep a space.
        body = f"{symbol} {formatted}"
    else:
        # Symbol prefix (e.g., "$1,234.56") — no space.
        body = f"{symbol}{formatted}"

    return f"-{body}" if is_negative else body
