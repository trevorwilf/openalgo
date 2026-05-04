"""T-28 (v7 Phase 7-bis) — Schwab broker plugin scaffold.

This is a real broker plugin entry (not the underscore-prefixed
``_mock_schwab_like`` framework-test fixture). The plugin.json
declares the full Schwab capability surface — venues / order
types / time-in-force / sessions / OAuth auth / account hashes /
subaccounts / WebSocket streaming.

What this plugin does NOT do (deferred to v8):
* Make real Schwab API calls. The api/ subpackage is empty in
  this scaffold; production code wires through Schwab's
  Charles-Schwab-Trader-API after the operator obtains official
  access.
* Real OAuth callback handling. The ``brlogin.py`` ``schwab/callback``
  pattern (proven for AliceBlue / Compositedge / IIFL Capital) is
  the integration point.
* Real order routing / quote / bar streaming.

What this plugin DOES today:
* Registers with the plugin loader so ``supported_regions=["us"]``
  brokers can be enumerated.
* Provides the v7 closing-invariant evidence that the framework
  hosts non-India broker plugins without silent India fallback.
* Exposes the canonical capability surface for any broker-
  agnostic UI / dispatcher / capability test that needs to query
  "what does Schwab support" before real API access is granted.

Per the prompt's stakeholder notes: real-API contract verification
is deferred until API access lands.
"""

from __future__ import annotations
