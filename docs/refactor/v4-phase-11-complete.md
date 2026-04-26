# v4 Phase 11 — Complete

* **Branch:** `refactor/v4-phase-11-mock-broker-e2e`
* **Merged:** to `dev` with `--no-ff`
* **Effort:** high

## Goal

Drive the mock plugins through every promoted lane end-to-end and
produce the framework-readiness evidence package. Confirm that real
Schwab and real Webull plugins can land without further core changes.

## Gaps closed (from `v3_baseline_audit.md`)

* **Gap 12** — mock Schwab-LIKE / Webull-LIKE end-to-end framework
  readiness fixtures. v3 Phase 6 introduced the mock plugins; v4
  Phase 11 confirms they cover every v4-added surface (strict
  plugin schema, position+balance adapter, sandbox/options/screener
  provider contracts, plugin diagnostics, v1 hard-block, framework
  readiness gate).

## What shipped

### `tests/contracts/test_framework_ready_for_real_brokers.py` — 13 tests

* `test_mock_plugin_strict_mode[_mock_schwab_like|_mock_webull_like]` —
  both pass strict promoted plugin schema.
* `test_mock_plugin_has_order_api[…]` — order translator surface
  exists.
* `test_mock_plugin_has_position_balance_adapters[…]` — Phase 5 v4
  adapters exist.
* `test_mock_plugin_has_stream_api[…]` — streaming surface exists.
* `test_mock_plugin_has_instrument_sync[…]` — instrument sync
  module exists.
* `test_v4_advanced_feature_contracts_loadable` — Sandbox /
  Options / Screener Protocols importable.
* `test_capability_dispatcher_contracts_loadable` — Order translator
  + Quote / Bar / Position / Balance adapter Protocols importable.
* `test_no_unfinished_promoted_TODO_markers` — no blocking TODOs
  in PROMOTED_CORE code.

### Schwab readiness package extension

`docs/refactor/schwab_readiness.md` extended with a v4
framework-readiness extension table covering strict plugin schema,
position+balance adapters, /api/v2/positions and /balances dispatch,
sandbox/options/screener providers, plugin diagnostics, v1 hard-
block, and the framework readiness gate.

### Webull readiness package extension

`docs/refactor/webull_readiness.md` extended with the same v4
framework-readiness extension table. Webull-specific carryovers
from v3 (SIGNATURE auth alongside OAUTH, sub-account semantics,
MQTT + gRPC streams) preserved.

### Statement of remaining work

Both readiness docs now state explicitly: **real Schwab / real Webull
plugin implementation remains the next-step work blocked on official
API validation.** v4 ships the framework; real plugins are out of v4
scope per the prompt.

## Comprehensive testing (gate 2.6)

| Step | Result |
|---|---|
| `pytest -x tests/contracts/ tests/parity/ tests/compliance/ tests/sandbox/ tests/options/ tests/screeners/` | 207 passed (no xfails) |
| `python tests/parity/run_parity.py` | 8/8 passed |
| `pytest tests/` | 2026 passed, 7 skipped — 161s |
| `npm run lint:literals` | 253 files / 0 violations |
| `python scripts/audit/classify_files.py --check` | 830 files / no drift |

All gates pass.

## Files touched

* Created: `tests/contracts/test_framework_ready_for_real_brokers.py`,
  this completion doc.
* Modified: `docs/refactor/schwab_readiness.md`,
  `docs/refactor/webull_readiness.md`.

## Phase 11 evidence summary

The framework can host real promoted-lane brokers (Schwab, Webull,
Alpaca, EU, UK, future) without further core changes:

* Strict promoted plugin schema (ADR 0025) accepts the contract.
* Order dispatcher + 5 adapter Protocols (Order, Quote, Bar,
  Position, Balance) cover order entry + read-side surfaces.
* Streaming Protocols (BrokerOrderEventStream,
  BrokerMarketDataStream) cover real-time surfaces (transports
  decoupled — websocket / MQTT / gRPC all proven by Webull mock).
* Sandbox / Options / Screener provider-pluggable contracts cover
  the four advanced features identified by the expert reviews.
* AccountContext with broker-specific fields (account_hash for
  Schwab, subaccount_id for Webull, entitlements for both) covers
  multi-account brokers.
* Plugin diagnostics endpoint surfaces operator-actionable load
  state.
* v1 hard-block prevents legacy India routes from reaching non-
  India brokers.
