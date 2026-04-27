# v5 Phase 6 — Complete

* **Branch:** `refactor/v5-phase-6-screener-dispatcher-migration`
* **Merged:** to `dev` with `--no-ff`
* **Effort:** max
* **Closes:** v4 deferral 10-bis (DB migration + capability + parity);
  expert MA-034; expert P7-07, P7-08, P7-09.

## Goal

Promote `BrokerCapabilities.supports_screener_providers`, ship the
additive `chartink_strategies` columns, and lock the India Chartink
provider's parity contract. The `blueprints/chartink.py` per-route
adoption of the dispatcher is the deferred Phase 6-bis follow-up.

## Work shipped

### `domain/capabilities.py` — `supports_screener_providers` field

* Added `supports_screener_providers: bool = False` to
  `BrokerCapabilities`.
* India inference defaults to True (Chartink webhooks have always
  worked for India brokers).
* Common defaults keep it False; non-India brokers must opt in.

### `frontend/src/types/capabilities.ts`

* Added `supports_screener_providers: boolean` to
  `BrokerCapabilities`.
* Extended `hasCapability` enum.

### Chartink DB additive columns

* `database/chartink_db.py` — added `provider_code` + `region_code`
  columns to `ChartinkStrategy` (nullable, both indexed).
* `upgrade/migrate_chartink_provider_columns.py` — new additive
  migration:
  * `add_chartink_provider_columns()` — idempotent up; ALTER TABLE
    adds columns, then conditionally backfills with
    `('chartink', 'india')`.
  * `revert_chartink_provider_backfill()` — down NULLs the
    backfill but **leaves the columns intact** (D-3, no DROP).

### `parity_chartink_india` harness — new (11th)

* `tests/parity/baseline/parity_chartink_india.{py,json}` —
  snapshots `ChartinkScreenerProvider`:
  * Validator output for three representative payloads (bullish
    breakout, bearish, single-stock-no-price).
  * Provider/region codes, supported venues.
* `tests/parity/run_parity.py::HARNESSES` extended; runner now
  reports **11/11 passed**.

### Tests

* `tests/plugin_loader/test_v5_supports_screener_capability.py` (4
  tests) — India inference, crypto stays-false, explicit override,
  default-unset.
* `tests/screeners/test_v5_chartink_provider_columns_migration.py`
  (3 tests) — up adds + backfills, idempotent re-run, down NULLs
  backfill but keeps columns.

## Out of scope (deferred to v5 Phase 6-bis)

The v5 prompt's other Phase 6 sub-items remain open and non-blocking:

1. `blueprints/chartink.py` route-by-route migration to
   `services/screeners/dispatcher.py`. The dispatcher and India
   provider are in place; per-route adoption is straightforward but
   touches many call sites. Today the India blueprint continues to
   drive the existing flow directly (parity-protected via the
   harness above).
2. Frontend `pages/chartink/**` capability gating —
   `caps.supports_screener_providers` is now exposed; the page
   adoption is per-PR and gated by the new field. Until the
   adoption ships, the existing India-classified pages render as
   before.
3. Webhook entry-point return of `unsupported_provider` for
   non-India active brokers — one-line addition once the blueprint
   adopts the dispatcher (Phase 6-bis).

## Gate results

| Step | Result |
|---|---|
| `uv run pytest tests/ -x --tb=short` | 2102 passed, 7 skipped, 0 failed |
| `uv run python tests/parity/run_parity.py` | 11/11 passed |
| `uv run python scripts/audit/classify_files.py --check` | 840 files, no drift |
| `uv run python scripts/audit/symtoken_callers.py` | 0 PROMOTED_LEAK |
| `npm run lint:literals` | 255 files, 0 violations |

All gates pass. Zero xfails added.

## v5 by the numbers (running total after Phase 6)

* **2 new ADRs** (0029, 0030 — Phase 1).
* **100 new tests** total (Phase 1: 23; Phase 2: 29; Phase 3: 22;
  Phase 4: 14; Phase 5: 5; Phase 6: 7).
* **2102 backend tests** (was 2095 at Phase 5 close; +7 net).
* **11 parity harnesses** (was 10 at Phase 5 close; +1 — `parity_chartink_india`).
* **3 net-new capability fields** (`supports_sandbox`,
  `supports_options`, `supports_screener_providers`).
* **0 PROMOTED_LEAK rows**.
* **0 frontend literal violations**.
