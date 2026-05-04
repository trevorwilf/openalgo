"""T-29 (v7 Phase 7-bis) — Webull broker plugin scaffold.

Same shape as the Schwab scaffold (T-28). The plugin.json
declares the Webull capability surface (venues including
CRYPTO; OAuth; WebSocket streaming; per-product fractional /
notional support). Real Webull API calls + OAuth wiring deferred
to v8 (blocked on official API access).

The ``_mock_webull_like`` underscore-prefixed plugin remains as
the framework-test fixture for the broker compliance harness.
"""

from __future__ import annotations
