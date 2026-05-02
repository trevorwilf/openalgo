# Phase 9-bis — Physical relocation playbook (T-23 future engagement)

This document is the migration playbook for moving the v1 lane
physically into `market_regions/india/legacy_v1/`.

**Status: not done in the main market-agnostic refactor pass
(2026-05-01 / 2026-05-02).** Phase 9 (logical) ships the
India-gated conditional mount and `OPENALGO_V1_SUNSET_DATE`
enforcement, which delivers the same operator-facing semantic.
The physical relocation is a code-quality follow-up.

## Why a future engagement (not a single-session pass)

* ~44 files moved from `restx_api/*.py` (excluding `restx_api/v2/`).
* `domain/translators.py` moves with them.
* `utils/constants.py` (the LEGACY_INDIA constants module) moves
  with them.
* Hundreds of import statements need updating across:
  * `app.py` — registers `api_v1_bp`.
  * `services/*.py` — imports `OrderSchema`, validators,
    `normalized_order_to_legacy_fields`, `VALID_*` constants.
  * `blueprints/*.py` — sandbox blueprint, telegram blueprint,
    etc.
  * `broker/*/api/*.py` — 30+ broker plugins import
    `utils.constants`.
  * `restx_api/__init__.py` — sets up the Flask-RESTX namespaces.
  * `tests/` — many test files import the schemas / translators.
* Internal `restx_api/*.py` cross-references (e.g. `from .schemas
  import OrderSchema`) continue to work post-move because they're
  relative; external imports (`from restx_api import api,
  api_v1_bp`) need rewriting OR a shim.

A wrong import = broken app at runtime, hard to catch via static
checks. The refactor needs:

1. Comprehensive integration testing under both `--lane v1` and
   `--lane v2` after each batch of moves.
2. Per-broker smoke testing (open the trading dashboard, place a
   sandbox order on each of the 30 India brokers).
3. Frontend tests if any UI code reaches into `restx_api/*` for
   types.

## Recommended migration steps

### Step 1 — Establish target

1. `market_regions/india/legacy_v1/__init__.py` already exists
   (Phase 9-bis stub).
2. Create `market_regions/india/legacy_v1/restx_api/` package
   directory with an `__init__.py`.

### Step 2 — Move in groups, not all at once

* **Group A — schemas only** (low blast radius first):
  - `restx_api/schemas.py`
  - `restx_api/data_schemas.py`
  - `restx_api/account_schema.py`
  Update every `from restx_api.schemas import OrderSchema` etc.
  across the codebase. Run parity. Run frontend.

* **Group B — translators + constants**:
  - `domain/translators.py`
  - `utils/constants.py`
  These are the broadest blast radius. ~30 broker plugins import
  `utils.constants`. Update imports broker-by-broker, run parity
  per broker.

* **Group C — endpoint route modules** (37 files):
  - The `restx_api/*.py` endpoint modules. Each one is
    self-contained (route handler + Marshmallow validation +
    service call). Move and update `restx_api/__init__.py`'s
    namespace registration to import from the new location.

* **Group D — `_v1_lane_guard.py`**:
  - Last to move because it's hooked via `before_request` /
    `after_request` on the blueprint.

### Step 3 — Re-export shim (decision point)

Two options:

* **Option A — pure relocation, no shim.** Every external
  importer of `restx_api`, `domain.translators`,
  `utils.constants` is rewritten. Cleanest but riskiest.

* **Option B — shim layer.** Keep `restx_api/__init__.py`,
  `domain/translators.py`, `utils/constants.py` as thin re-export
  modules pointing at `market_regions.india.legacy_v1.*`. External
  importers continue working without changes.

Option B is the safer single-engagement move. Once shipped,
follow-up engagements can incrementally migrate importers to the
new path and remove the shim.

### Step 4 — Update classification rules

`scripts/audit/classification_rules.yaml`:

* Add `path_prefix: market_regions/india/legacy_v1/` →
  `REGION_PLUGIN` (overriding default `LEGACY_INDIA` for files
  there).
* Drop the explicit per-file `LEGACY_INDIA` rules for
  `restx_api/*.py` since they're now under
  `market_regions/india/legacy_v1/`.

`scripts/audit/classify_files.py --check` should show the
`LEGACY_INDIA` bucket reduce from ~211 files to <50 (the prompt's
T-35 acceptance).

### Step 5 — Update Phase 9 logical conditional

`app.py` currently has:

```python
if get_market_region("india") is not None:
    app.register_blueprint(api_v1_bp)
```

Post-physical-move, `api_v1_bp` is imported from
`market_regions.india.legacy_v1.restx_api`. Same conditional
applies.

## Estimated effort

* 1 engineer × 5 working days for the full migration + integration
  testing.
* Could be parallelized into Group A (1d), Group B (2d), Group C
  (1.5d), Group D + cleanup (0.5d).

## Risk register

* **Highest risk:** missed imports break the app at runtime.
  Mitigation: extensive `pytest tests/ -q` + manual smoke testing
  after each group.
* **Medium risk:** circular imports surface (already a known
  pre-existing issue with `place_order_service` → `restx_api`
  → `options_multiorder` → `place_order_service`). Mitigation:
  resolve before the move, not during.
* **Low risk:** Frontend type imports break. Mitigation:
  `npx tsc --noEmit` after schema move.

## Definition of done

* All files relocated (or shimmed).
* `LEGACY_INDIA` bucket size <50 in
  `docs/refactor/file_classification.md`.
* `tests/parity/baseline/` — 41/41 green on both lanes, including
  with `API_V2_<BROKER>=1` enabled per the Phase 6 ALL_GREEN
  status.
* `tests/contracts/test_lane_isolation.py` and
  `test_v6_closing_invariants.py` green.
* `dev` branch runs the trading dashboard end-to-end (manual
  smoke test).
