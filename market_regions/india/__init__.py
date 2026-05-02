"""India region plugin — Python package.

Phase 2 of the market-agnostic refactor builds out
``market_regions/india/`` as a real Python package alongside the
existing ``plugin.json`` manifest. Modules in this package OWN the
India-specific data tables and grammar; consumers (sandbox engine,
options services, market-calendar seeder, locale formatters) import
from here instead of carrying the constants inline.

Module map:
* :mod:`market_regions.india.holidays` — holiday calendar and
  special sessions (T-09).
* :mod:`market_regions.india.sessions` — Asia/Kolkata timezone
  object exposed once for the rest of the codebase to import
  (T-10).
* :mod:`market_regions.india.squareoff` — MIS auto-square-off
  rules per venue (T-11).
* :mod:`market_regions.india.qty_freeze` — NFO quantity-freeze
  table (T-12).
* :mod:`market_regions.india.options_grammar` — DDMMMYY parse
  pattern, CE/PE rights, lot-size table, NSE_INDEX/BSE_INDEX
  classification, equity-index expiry cutoff (T-14 data).
* :mod:`market_regions.india.locale` — Indian-currency / number
  formatters and ``Currency``/locale tag (T-15).
"""

from __future__ import annotations
