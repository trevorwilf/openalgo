# v4 Phase 4 — Complete

* **Branch:** `refactor/v4-phase-4-broker-strict`
* **Merged:** to `dev` with `--no-ff`
* **Effort:** high

## Goal

Make `plugin.json` for promoted brokers strictly validated. Unknown
fields become errors. Required promoted fields are enforced. Plugin
diagnostics endpoint exposes loader state for operators.

## Invariants enforced

* **Invariant 6** — promoted plugin schema is strict. Phase 1's
  `test_v4_promoted_plugin_strict_mode.py` xfail removed; the test
  is now a passing regression contract.

## What shipped

### `utils/plugin_loader.py` — strict-mode validator

* `_V4_PROMOTED_REQUIRED_FIELDS` — 17 required-for-promoted fields:
  `broker_code`, `broker_display_name`, `broker_type`,
  `supported_regions`, `market_families`, `supported_venue_codes`,
  `supported_asset_classes`, `supported_order_types`,
  `supported_time_in_force`, `supported_sessions`,
  `supported_quantity_units`, `trading_currencies`,
  `default_currency`, `base_currency`, `auth_modes`,
  `account_context_supports`, `master_contract_refresh_policy`.
* `_OPTIONAL_PROMOTED_FIELDS` — explicitly allowed operational fields
  (combo support, streaming, sandbox, options, screener, etc.).
* `_strict_promoted_plugin_errors` — rejects missing required fields
  AND unknown fields for promoted plugins (`additionalProperties: false`
  equivalent).
* `_is_promoted_plugin` — explicit `promoted: true` OR
  `supported_regions` excludes `"india"`.
* `_plugin_diagnostics` + `get_plugin_diagnostics` — per-broker state
  dict populated at load time.
* Loader gates are tiered:
  1. JSON Schema validation (existing).
  2. Phase 3 completeness check (existing).
  3. Phase 4 v4 strict mode (new).

  All three respect `STRICT_CAPABILITY_INFERENCE=0` for the rollback
  escape hatch.

### `restx_api/v2/plugins.py` — diagnostics endpoint

* `GET /api/v2/plugins/diagnostics` returns:
  * Top-level `summary`: `loaded`, `loaded_with_warnings`, `skipped`,
    `promoted_loaded`.
  * `brokers` map keyed on broker_code with `state`, `promoted`,
    `broker_type`, `supported_regions`, plus `reason` / `errors` /
    `missing_fields` for skipped brokers.

### Plugin updates

* `broker/alpaca/plugin.json` — added `broker_code` and
  `account_context_supports` so the real promoted broker passes
  strict mode. Existing fields unchanged.
* Mock Schwab and mock Webull already had every required v4 field;
  no plugin edits needed.

## New tests added

| File | Tests |
|---|---|
| `tests/plugin_loader/test_strict_promoted_schema.py` | 7 (Alpaca/Schwab/Webull pass strict; legacy India bypass; missing-required and unknown-field violations; explicit promoted marker) |
| `tests/plugin_loader/test_diagnostics_endpoint.py` | 2 (summary shape; empty state) |
| **Total new** | **9** |

## Test fixtures updated

* `tests/plugin_loader/test_capability_completeness.py` — `_full_us`
  fixture now includes the 3 new v4 promoted fields (`broker_code`,
  `broker_display_name`, `account_context_supports`).
* `tests/plugin_loader/test_supported_regions.py` —
  `custom_region` fixture updated similarly.
* `tests/contracts/test_v4_promoted_plugin_strict_mode.py` — xfail
  marker removed; test now enforces invariant.

## Comprehensive testing (gate 2.6)

| Step | Result |
|---|---|
| `pytest -x tests/contracts/ tests/parity/ tests/compliance/ tests/plugin_loader/` | 267 passed, 6 skipped, 3 xfailed — 9s |
| `python tests/parity/run_parity.py` | 7/7 passed |
| `pytest tests/` | 1904 passed, 7 skipped, 3 xfailed — 157s |
| `npm run lint:literals` | 253 files / 0 violations |
| `python scripts/audit/classify_files.py --check` | 814 files / no drift |
| `python scripts/audit/route_fallback_scan.py` | 50 routes |
| `python scripts/audit/symtoken_callers.py` | 0 PROMOTED_LEAK rows |

All gates pass.

## Files touched

* Modified: `utils/plugin_loader.py`, `restx_api/v2/__init__.py`,
  `broker/alpaca/plugin.json`,
  `tests/plugin_loader/test_capability_completeness.py`,
  `tests/plugin_loader/test_supported_regions.py`,
  `tests/contracts/test_v4_promoted_plugin_strict_mode.py`,
  `docs/refactor/file_classification.md` (regen).
* Created: `restx_api/v2/plugins.py`,
  `tests/plugin_loader/test_strict_promoted_schema.py`,
  `tests/plugin_loader/test_diagnostics_endpoint.py`,
  `docs/adr/0025-strict-promoted-plugin-schema.md`, this completion doc.

## ADRs

* **0025** — Strict-mode schema for promoted broker plugins.

## Deferred follow-ups

* Required-adapter-registration check (work item 6 of Phase 4 in the
  v4 prompt) — partial: the diagnostics endpoint surfaces every
  broker's state, but the per-feature adapter check (declared trading
  capability without registered translator → "metadata-only") is more
  natural to land in Phase 5 alongside the v2 read-side adapter
  registry. Reserved for Phase 5.
* Required adapter registration matrix in
  `docs/refactor/broker_compliance_matrix.md` — regenerate after
  Phase 5/11 adapter completeness work.
