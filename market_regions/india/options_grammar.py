"""India options-grammar data tables — Phase 2 T-14 relocation.

Source of truth for the India option-symbol grammar:

* DDMMMYY date format (``"%d%b%y"``) — e.g. ``28OCT25``.
* Right codes: ``CE`` (CALL), ``PE`` (PUT).
* Symbol pattern: ``<underlying><DDMMMYY><strike><CE|PE>`` with the
  underlying being the longest non-digit prefix.
* Default venue code (``NFO``) and currency (``INR``).
* Lot-size table for representative indices.
* Index venue classification — ``NSE_INDEX`` / ``BSE_INDEX``.
* Black-76 expiry-cutoff: India equity / index options stop trading at
  15:30 IST on expiry day. (Currency expiries close at 12:30 IST; this
  module records the equity/index value used by the options pricing
  pipeline.)

Relocated byte-equivalently from the inline literals in
``services.options.providers.india`` and the legacy options services
(``services.option_symbol_service``,
``services.option_chain_service``). Those modules remain as the live
entry points; the ``IndiaOptionsProvider`` continues to drive the
parser/formatter logic — only the *data* is region-owned now.
"""

from __future__ import annotations

import re
from typing import Any


DATE_FORMAT: str = "%d%b%y"
"""``strptime`` / ``strftime`` format string for India option expiries."""

RIGHT_CODES: dict[str, str] = {"CE": "CALL", "PE": "PUT"}
"""Mapping from India wire-level right codes to the canonical
:class:`domain.options.OptionRight` value names."""

DEFAULT_VENUE_CODE: str = "NFO"
"""Default venue an India option contract maps to in the parser."""

DEFAULT_CURRENCY: str = "INR"
"""Currency for India option contracts."""


# Pattern: <underlying><DDMMMYY><strike><CE|PE>. Underlying is the
# longest non-digit prefix. DDMMMYY is exactly 7 chars
# (2 digits + 3 letters + 2 digits). Strike may have a decimal.
SYMBOL_PATTERN: re.Pattern[str] = re.compile(
    r"^(?P<underlying>[A-Z]+)"
    r"(?P<expiry>\d{2}[A-Z]{3}\d{2})"
    r"(?P<strike>\d+(?:\.\d+)?)"
    r"(?P<right>CE|PE)$"
)


# Lot sizes for representative India indices/stocks. Real lot sizes
# come from the master contract; this static map is the parity-
# preserving default for sandbox / framework-readiness coverage.
LOT_SIZES: dict[str, int] = {
    "NIFTY": 50,
    "BANKNIFTY": 15,
    "FINNIFTY": 25,
    "MIDCPNIFTY": 75,
    "SENSEX": 10,
    "BANKEX": 15,
}


# Venue → list of corresponding index venue codes for India. Used by
# the index classifier in the options pipeline to route INDEX requests
# to the dedicated index venue.
INDEX_CLASSIFICATION: dict[str, list[str]] = {
    "NSE": ["NSE_INDEX"],
    "BSE": ["BSE_INDEX"],
}


# Equity/index option last-trade time on expiry day (HH:MM in venue
# timezone — Asia/Kolkata). Currency options stop earlier (12:30); this
# constant captures the dominant equity-index cutoff that the Black-76
# pipeline reads for time-to-expiry computation.
EQUITY_INDEX_EXPIRY_CUTOFF_HHMM: tuple[int, int] = (15, 30)


# Aggregate dict shape that ``MarketRegion.option_grammar`` consumers
# (Phase 0 T-01 schema field) read at load time.
OPTION_GRAMMAR: dict[str, Any] = {
    "date_format": DATE_FORMAT,
    "right_codes": dict(RIGHT_CODES),
    "default_venue_code": DEFAULT_VENUE_CODE,
    "default_currency": DEFAULT_CURRENCY,
    "symbol_pattern": SYMBOL_PATTERN.pattern,
    "lot_sizes": dict(LOT_SIZES),
    "index_classification": dict(INDEX_CLASSIFICATION),
    "equity_index_expiry_cutoff_hhmm": EQUITY_INDEX_EXPIRY_CUTOFF_HHMM,
}


__all__ = [
    "DATE_FORMAT",
    "DEFAULT_CURRENCY",
    "DEFAULT_VENUE_CODE",
    "EQUITY_INDEX_EXPIRY_CUTOFF_HHMM",
    "INDEX_CLASSIFICATION",
    "LOT_SIZES",
    "OPTION_GRAMMAR",
    "RIGHT_CODES",
    "SYMBOL_PATTERN",
]
