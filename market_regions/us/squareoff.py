"""US mandatory-close rules — Phase 2 T-11 parallel example.

Mirror of :mod:`market_regions.india.squareoff` for the US region. The
US sandbox provider (``services.sandbox.providers.us``) carries the
runtime ``_DAY_TRADE_CLOSE_HHMM = (16, 0)`` constant inline today; this
module exposes the same fact in the
``MarketRegion.mandatory_close_rules``-shaped form the schema added in
Phase 0 T-01 expects.

This is data only — Phase 2 does NOT wire any US engine through this
table. Phase 7 (Build out India + US region plugin implementations)
owns the live wiring of the US sandbox engine. The US data file lives
here so that:

* The schema-validation tests in :mod:`tests.region_loader` can confirm
  every region carries a ``mandatory_close_rules`` payload of the same
  shape.
* When Phase 7 adds the live US sandbox engine, the runtime reads from
  here rather than re-declaring the rule table inline.
"""

from __future__ import annotations

from typing import Any


# 16:00 ET is the US regular-session close. The DAY_TRADE product
# (the US analog of India's MIS auto-square-off semantics) closes at
# regular-session close. PRE_MARKET / POST_MARKET sessions exist but
# are not subject to mandatory close — their windows are defined in
# market_regions/us/sessions.py (or the US plugin.json manifest).
MANDATORY_CLOSE_RULES: list[dict[str, Any]] = [
    {"venue": "XNYS", "local_close": "16:00", "applies_to": ["DAY_TRADE"]},
    {"venue": "XNAS", "local_close": "16:00", "applies_to": ["DAY_TRADE"]},
    {"venue": "ARCX", "local_close": "16:00", "applies_to": ["DAY_TRADE"]},
    {"venue": "BATS", "local_close": "16:00", "applies_to": ["DAY_TRADE"]},
]


__all__ = ["MANDATORY_CLOSE_RULES"]
