"""US options grammar — Phase 7b T-30 build-out.

OCC OSI 21-character format
(https://www.theocc.com/Company-Information/Documents-and-Archives/Options-Symbology):

    <root[6]><yymmdd[6]><C/P[1]><strike_dollars[5]><strike_decimals[3]>

Example: ``AAPL  240419C00185000`` →
   underlying=AAPL, expiry=2024-04-19, right=CALL, strike=185.000.

The runtime parser/formatter live at
:mod:`services.options.providers.us`. This module owns the **data
tables**:

* ``DATE_FORMAT`` — ``%y%m%d`` (the OSI date sub-string format).
* ``RIGHT_CODES`` — ``C`` → CALL, ``P`` → PUT.
* ``DEFAULT_VENUE_CODE`` — ``OPRA`` (the consolidated US options tape).
* ``DEFAULT_CURRENCY`` — ``USD``.
* ``LOT_SIZE`` — 100 (standard US contract multiplier).
* ``EQUITY_INDEX_EXPIRY_CUTOFF_HHMM`` — 16:00 ET (regular-session close).
"""

from __future__ import annotations

import re
from typing import Any


DATE_FORMAT: str = "%y%m%d"
"""``strptime`` / ``strftime`` format for the OSI date sub-string."""

RIGHT_CODES: dict[str, str] = {"C": "CALL", "P": "PUT"}
"""Mapping from OSI right codes to the canonical
:class:`domain.options.OptionRight` value names."""

DEFAULT_VENUE_CODE: str = "OPRA"
"""Consolidated US options tape; individual broker plugins may map
this to their own exchange code (NASDAQ ISE, CBOE, BOX, etc.)."""

DEFAULT_CURRENCY: str = "USD"

LOT_SIZE: int = 100
"""Standard US options contract multiplier."""

# Regex pattern for OSI 21-char strings. Underlying may include
# spaces (right-padded to 6 chars in the canonical OSI form). We
# accept the trimmed form (no padding) too because most broker APIs
# normalize the underlying.
SYMBOL_PATTERN: re.Pattern[str] = re.compile(
    r"^(?P<underlying>[A-Z0-9]{1,6})\s*"
    r"(?P<expiry>\d{6})"
    r"(?P<right>[CP])"
    r"(?P<strike>\d{8})$"
)


# US index symbol classifications. US indices share the equity venue
# codes (^SPX trades through XNAS, ^NDX through XNAS). No separate
# "INDEX" venue codes like India's NSE_INDEX.
INDEX_CLASSIFICATION: dict[str, list[str]] = {}


# Equity / index option expiry cutoff. NYSE/NASDAQ regular session
# close is 16:00 ET; options stop trading at 16:15 ET for index
# options and 16:00 ET for equity options. This module captures the
# dominant equity-option cutoff used by the Black-Scholes pipeline.
EQUITY_INDEX_EXPIRY_CUTOFF_HHMM: tuple[int, int] = (16, 0)


# Aggregate dict shape that ``MarketRegion.option_grammar`` consumers
# read at load time.
OPTION_GRAMMAR: dict[str, Any] = {
    "date_format": DATE_FORMAT,
    "right_codes": dict(RIGHT_CODES),
    "default_venue_code": DEFAULT_VENUE_CODE,
    "default_currency": DEFAULT_CURRENCY,
    "symbol_pattern": SYMBOL_PATTERN.pattern,
    "lot_size": LOT_SIZE,
    "index_classification": dict(INDEX_CLASSIFICATION),
    "equity_index_expiry_cutoff_hhmm": EQUITY_INDEX_EXPIRY_CUTOFF_HHMM,
}


__all__ = [
    "DATE_FORMAT",
    "DEFAULT_CURRENCY",
    "DEFAULT_VENUE_CODE",
    "EQUITY_INDEX_EXPIRY_CUTOFF_HHMM",
    "INDEX_CLASSIFICATION",
    "LOT_SIZE",
    "OPTION_GRAMMAR",
    "RIGHT_CODES",
    "SYMBOL_PATTERN",
]
