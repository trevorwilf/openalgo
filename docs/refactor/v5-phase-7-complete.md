# v5 Phase 7 — Complete

* **Branch:** `refactor/v5-phase-7-capability-and-account-context`
* **Merged:** to `dev` with `--no-ff`
* **Effort:** high
* **Closes:** expert MA-007, MA-022, MA-023, MA-024, MA-025, MA-037;
  expert P3-01…P3-06, P8-01, P8-03, P8-04.

## Goal

Lock the broker capability surface so every advertised capability is
executable end-to-end and account-context-aware. The combo capability
single-source decision is the load-bearing fix; account-context
entitlement plumbing locks the v6 broker-readiness path.

## Work shipped

### Combo capability single source

Both expert reviews flagged drift between top-level
`supports_combo_types` (mock plugin JSON) and per-asset
`ProductCapabilities.supports_combo_types` (runtime model). v5
Phase 7 picks the **top-level** as canonical:

* Added `BrokerCapabilities.supports_combo_types: list[ComboType]`
  (default empty list).
* `ProductCapabilities.supports_combo_types` retained for per-asset
  overrides.
* `_EXPLICIT_OVERRIDE_KEYS` extended to include the new field.
* `frontend/src/types/capabilities.ts` extended with
  `supports_combo_types?: string[]`.
* New contract test
  `tests/contracts/test_v5_combo_capability_single_source.py` (6
  tests):
  * Top-level field exists and accepts ComboType values.
  * Per-product field still exists.
  * Top-level default is empty list.
  * Both mock plugin JSONs (Schwab-LIKE, Webull-LIKE) declare
    the field at top level.
  * `restx_api/v2/orders_combo.py` reads the top-level field.

The drift pre-Phase-7 meant `caps.supports_combo_types` returned
`None` (BrokerCapabilities had no such field), so the `if supported
and ...` gate fell through silently. With this fix the gate fires
correctly.

### Account context entitlement contract

* `domain/account_context.py::AccountContext.entitlements` already
  exists; v5 Phase 7 locks the contract via tests:
  * `tests/domain/test_v5_account_context_entitlements.py` (9 tests).
  * Defaults, set-via-constructor, base_currency from `Currency`,
    `from_legacy_dict` preserving entitlements, frozen model
    enforcement, `EntitlementRequired` (Phase 1) wiring.

### Already-in-place pieces (verified)

The v5 prompt enumerated 6 sub-items for this phase. The drift fix
above is the load-bearing core. The remaining items are already
satisfied by prior phases:

* **Native product map** — `BrokerCapabilities.products[*]` already
  carries per-asset product metadata from v4 Phase 4. Lane scanner
  reports zero `MIS|CNC|NRML` in PROMOTED_CORE.
* **Account context entitlements** — `AccountContext.entitlements`
  + `EntitlementRequired` (Phase 1) + `from_legacy_dict` shim are
  in place. Per-route admission wiring (the broker-side
  enforcement) is v6 work tied to real broker plugins.
* **Streaming registry hardening** — `domain/broker_streaming.py`
  + `services/broker_streaming_registry.py` exist (v4). Mock
  Schwab/Webull plugins exercise the contract. Lifecycle tests
  expand in Phase 10 closing audit.
* **Capability prechecks for v2 routes** — `restx_api/v2/orders.py`,
  `orders_combo.py`, `quotes.py`, `bars.py` all check capabilities
  before any broker network call. The new `unsupported_capability`
  + `dimension` (ADR 0029) is available for any new gate.
* **Capability schema enforcement at plugin load** — v4 Phase 4
  strict-mode loader rejects promoted plugins missing required
  fields. Existing tests cover this.

## Gate results

| Step | Result |
|---|---|
| `uv run pytest tests/ -x --tb=short` | 2117 passed, 7 skipped, 0 failed |
| `uv run python tests/parity/run_parity.py` | 11/11 passed |
| `uv run python scripts/audit/classify_files.py --check` | 840 files, no drift |
| `uv run python scripts/audit/symtoken_callers.py` | 0 PROMOTED_LEAK |
| `npm run lint:literals` | 255 files, 0 violations |

All gates pass. Zero xfails added.

## v5 by the numbers (running total after Phase 7)

* **2 new ADRs** (0029, 0030 — Phase 1).
* **115 new tests** total (Phase 1: 23; Phase 2: 29; Phase 3: 22;
  Phase 4: 14; Phase 5: 5; Phase 6: 7; Phase 7: 15).
* **2117 backend tests** (was 2102 at Phase 6 close; +15 net).
* **11 parity harnesses** (unchanged).
* **4 net-new capability fields** (`supports_sandbox`,
  `supports_options`, `supports_screener_providers`,
  `supports_combo_types`).
* **0 PROMOTED_LEAK rows**.
* **0 frontend literal violations**.
