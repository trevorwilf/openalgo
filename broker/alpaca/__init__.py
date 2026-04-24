"""Alpaca broker — promoted-lane adapter (US cash equities).

Markers:
- This adapter is PROMOTED: `broker/alpaca/PROMOTED` sentinel file
  signals to the lane-isolation test that this directory must not
  import any legacy symbols (VALID_EXCHANGES, get_token,
  normalized_order_to_legacy_fields, quotes_service, history_service).
"""

from __future__ import annotations
