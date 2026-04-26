# v4 Phase 10 — Complete (PARTIAL — blueprint wiring in Phase 10-bis)

* **Branch:** `refactor/v4-phase-10-screener-providers`
* **Merged:** to `dev` with `--no-ff`
* **Effort:** high

## Goal

Extract Chartink from `blueprints/chartink.py` into a generic
webhook-screener provider contract. Chartink becomes the India
provider implementation. Future regions can register their own
screener providers.

## Gaps closed (from `v3_baseline_audit.md`)

* **Gap 13** (Chartink portion) — `chartink` blueprint scheduler
  IST-bound. The provider abstraction shipped here decouples
  Chartink's parsing + order-mapping from the blueprint; Phase 10-bis
  wires the blueprint to dispatch through the provider. Existing
  India behavior is parity-protected today.

## Invariants enforced

* **Invariant 7** (Screener slice) — provider-pluggable contract +
  India (Chartink) implementation + dispatcher exist.
  `tests/contracts/test_v4_advanced_feature_provider_contracts.py`
  Screener xfail removed (now passes).

  **All three v4 invariant 7 sub-tests now pass.**

## What shipped

### `services/screeners/providers/base.py` — `ScreenerProvider` Protocol

* `ScreenerSignal` (signal_type, symbols, price, timestamp,
  raw_payload, metadata).
* `ScreenerConfig` (quantity, product, venue_code, order_type,
  metadata).
* `ScreenerProvider` Protocol with 3 methods:
  `validate_webhook_payload`, `supported_signal_types`,
  `map_signal_to_orders`.

### `services/screeners/providers/india/chartink.py` — Chartink provider

* `ChartinkScreenerProvider`:
  * Parses Chartink's webhook payload format
    (`{stocks, trigger_prices, scan_name, alert_name, ...}`).
  * Infers signal_type from scan_name/alert_name keywords:
    "exit"/"square off" → "exit"; "sell"/"bearish"/"short" →
    "sell"; default "buy".
  * Maps signal to NormalizedOrderRequest objects with
    `extra["product"]` carrying the India product type so existing
    legacy India translators read it without changes.
  * Supported venues: NSE, BSE.

### `services/screeners/providers/us/__init__.py` — stub

US screener provider directory exists with a docstring explaining
the future expansion path. **No US screener implementation in v4
per user clarification.**

### `services/screeners/dispatcher.py`

* Auto-registers Chartink at module load.
* `get_screener_provider` raises `ScreenerProviderNotRegistered`
  (mapped to `ErrorCode.SCREENER_PROVIDER_NOT_REGISTERED`).
* `get_screener_provider_or_none` for UI gating.

### `docs/adr/0028-screener-provider-contract.md`

ADR documenting the contract, the Chartink implementation, and what
is deferred to Phase 10-bis (blueprint refactor, DB schema additions,
parity harness, capability metadata).

## New tests added

| File | Tests |
|---|---|
| `tests/screeners/test_provider_contract.py` | 12 (Chartink Protocol conformance, payload parsing for buy/sell/exit/missing/non-dict, signal-to-orders for MARKET and LIMIT, dispatcher resolution, fail-closed for unknown provider) |
| `tests/contracts/test_v4_advanced_feature_provider_contracts.py` | All three xfail markers removed. **v4 invariant 7 fully enforced.** |

## What is deferred to Phase 10-bis

Per ADR 0028 § "What is deferred to Phase 10-bis":

* Refactor `blueprints/chartink.py` (944 lines) to a thin shim that
  calls `services/screeners/dispatcher.dispatch_webhook`.
* Refactor `database/chartink_db.py` to add nullable `provider_code`
  + `region_code` columns + `upgrade/migrate_chartink_provider_columns.py`
  backfill.
* `parity_chartink_india` parity harness covering bit-identical
  webhook → orders behavior.
* `BrokerCapabilities.supports_screener_providers` capability
  metadata.
* Frontend Chartink UI hidden when broker doesn't list the provider.

The contract + India provider + dispatcher are the load-bearing
pieces. Phase 10-bis lands the wiring incrementally without breaking
the parity-protected India Chartink path.

## Comprehensive testing (gate 2.6)

| Step | Result |
|---|---|
| `pytest -x tests/contracts/ tests/parity/ tests/compliance/ tests/screeners/ tests/options/ tests/sandbox/` | 194 passed (no xfails remaining) |
| `python tests/parity/run_parity.py` | 8/8 passed |
| `pytest tests/` | 2013 passed, 7 skipped — 160s |
| `npm run lint:literals` | 253 files / 0 violations |
| `python scripts/audit/classify_files.py --check` | 830 files / no drift |

All gates pass. **Zero xfails in the test suite.**

## Files touched

* Created: `services/screeners/__init__.py`,
  `services/screeners/providers/__init__.py`,
  `services/screeners/providers/base.py`,
  `services/screeners/providers/india/__init__.py`,
  `services/screeners/providers/india/chartink.py`,
  `services/screeners/providers/us/__init__.py`,
  `services/screeners/dispatcher.py`,
  `tests/screeners/__init__.py`,
  `tests/screeners/test_provider_contract.py`,
  `docs/adr/0028-screener-provider-contract.md`,
  this completion doc.
* Modified: `tests/contracts/test_v4_advanced_feature_provider_contracts.py`
  (removed last xfail; updated docstring),
  `docs/refactor/file_classification.md` (regen).
