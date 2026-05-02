"""US region plugin — Python package.

Phase 7b builds out ``market_regions/us/`` as a real Python package
alongside the existing ``plugin.json`` manifest. Modules here own the
US-specific data tables and grammar; consumers (US sandbox engine,
US options provider, calendar seeder, locale formatters) import from
here instead of carrying the constants inline.

Module map:

* :mod:`market_regions.us.holidays` — NYSE/NASDAQ market holidays
  (federal holidays + early-close days for 2024-2027).
* :mod:`market_regions.us.sessions` — America/New_York timezone +
  session windows (PRE_MARKET / REGULAR / POST_MARKET).
* :mod:`market_regions.us.squareoff` — DAY_TRADE close at 16:00 ET.
* :mod:`market_regions.us.qty_freeze` — empty (no US equivalent of
  India's NFO freeze table).
* :mod:`market_regions.us.options_grammar` — OCC OSI 21-character
  format data tables.
* :mod:`market_regions.us.locale` — USD currency formatter.
* :mod:`market_regions.us.settlement` — T+1 (post-May 2024 SEC rule).
* :mod:`market_regions.us.plugin` — :class:`USRegionPlugin` that
  composes the data modules into a ``RegionPlugin``-shaped object.
"""

from __future__ import annotations
