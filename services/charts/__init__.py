"""Phase 1 — Datafeed Foundation (services/charts/).

Region-neutral chart datafeed services. PROMOTED_CORE classification:
no India literals, no legacy imports, broker-agnostic.

Public modules:

* :mod:`services.charts.normalized_bar` — Decimal/UTC-seconds bar shape.
* :mod:`services.charts.intervals_service` — canonical interval enum +
  per-broker translation. (Distinct from the v1-lane
  ``services.intervals_service``.)
* :mod:`services.charts.bar_resampler` — DuckDB → Polars resampler.
* :mod:`services.charts.ws_envelope` — WebSocket envelope contract.
* :mod:`services.charts.valkey_client` — Valkey/Redis connection helper.
"""

from __future__ import annotations
