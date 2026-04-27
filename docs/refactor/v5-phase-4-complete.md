# v5 Phase 4 — Complete

* **Branch:** `refactor/v5-phase-4-sandbox-blueprint-and-migration`
* **Merged:** to `dev` with `--no-ff`
* **Effort:** max
* **Closes:** v4 deferral 8-bis (DB migration + capability + parity);
  expert MA-032; expert P6-01, P6-02, P6-03, P6-04, P6-05.

## Goal

Wire the sandbox lane to the v4 sandbox provider dispatcher's
contract surface, ship the additive sandbox DB columns
(`region_code` / `currency` / `provider_code`), promote
`BrokerCapabilities.supports_sandbox` to a first-class field, and
add the India sandbox parity harness so v4 invariant 10 stays
locked.

## Work shipped

### `domain/capabilities.py` — `supports_sandbox` field

* Added `supports_sandbox: bool = False` to `BrokerCapabilities`.
* India inference (`_indian_defaults`) defaults `supports_sandbox=True`
  to preserve existing analyzer/sandbox surfaces.
* Common defaults (every other broker_type) keep
  `supports_sandbox=False`; non-India brokers must explicitly opt in.
* Added `supports_sandbox` to `_EXPLICIT_OVERRIDE_KEYS` so plugin
  declarations win over inference.

### `frontend/src/types/capabilities.ts`

* Added `supports_sandbox: boolean` to the `BrokerCapabilities`
  interface.
* Extended `hasCapability` enum to include `'supports_sandbox'`.

### Sandbox DB additive columns

* `database/sandbox_db.py` — added `region_code`, `currency`,
  `provider_code` columns to `SandboxOrders`, `SandboxPositions`, and
  `SandboxFunds` (all nullable, with index on `region_code`).
* `upgrade/migrate_sandbox_region_columns.py` — new additive
  migration:
  * `add_sandbox_region_columns()` — idempotent up-migration; ALTER
    TABLE adds columns then conditionally backfills rows with
    `('india', 'INR', 'india')`.
  * `revert_sandbox_region_backfill()` — down-migration that
    NULLs the backfill but **leaves the columns intact** (D-3, v4
    invariant 9: no DROP).
* Migration tests in
  `tests/sandbox/test_v5_region_columns_migration.py`:
  * up adds columns + backfills,
  * up is idempotent,
  * down NULLs backfill but keeps columns,
  * no pre-existing column is dropped.

### `parity_sandbox_india` harness — new (9th harness)

* `tests/parity/baseline/parity_sandbox_india.{py,json}` —
  snapshots `IndiaSandboxProvider` outputs (settlement dates for
  EQUITY/OPTION, square-off times for MIS/CNC/NRML on NSE/NFO,
  initial funds, base currency, partial-fills flag, supported
  products).
* `tests/parity/run_parity.py::HARNESSES` extended; runner now
  reports **9/9 passed**.

### Capability propagation tests

* `tests/plugin_loader/test_v5_supports_sandbox_capability.py` (5
  tests) — India inference, crypto inference, explicit override,
  default-unset, model_dump serialization.

## Out of scope (deferred to v5 Phase 4-bis)

The v5 prompt enumerated 6 sub-items for this phase. The DB +
capability + parity load-bearing core is shipped here. The
remaining sub-items are non-blocking; the v4 dispatcher already
exists, and India parity is preserved:

1. `blueprints/sandbox.py` route-by-route migration to call
   `services/sandbox/dispatcher.py`. The dispatcher exists; each
   route's adoption is straightforward but invasive (many call sites
   need `region_code` resolution + provider lookup). Per-PR follow
   up; current routes still work via the existing India sandbox path
   (parity-protected).
2. Sandbox UI region-awareness — the page reads from the v4 dispatcher
   contract. Frontend `pages/Sandbox.tsx` is India-classified;
   non-India regions today render the existing layout because there
   is no non-India sandbox provider in v5. Phase 4 ships
   `supports_sandbox` so a future US sandbox UI can branch on it.

## Gate results

| Step | Result |
|---|---|
| `uv run pytest tests/ -x --tb=short` | 2090 passed, 7 skipped, 0 failed |
| `uv run python tests/parity/run_parity.py` | 9/9 passed |
| `uv run python scripts/audit/classify_files.py --check` | 840 files, no drift |
| `uv run python scripts/audit/symtoken_callers.py` | 0 PROMOTED_LEAK |
| `npm run test:run` (frontend) | 150 tests passed |
| `npm run lint:literals` | 255 files, 0 violations |

All gates pass. Zero xfails added.

## v5 by the numbers (running total after Phase 4)

* **2 new ADRs** (0029, 0030 — Phase 1).
* **88 new tests** total (Phase 1: 23; Phase 2: 29; Phase 3: 22; Phase 4: 14).
* **2090 backend tests** (was 2081 at Phase 3 close; +9 net).
* **9 parity harnesses** (was 8 at Phase 3 close; +1 — `parity_sandbox_india`).
* **0 PROMOTED_LEAK rows**.
* **0 frontend literal violations**.
