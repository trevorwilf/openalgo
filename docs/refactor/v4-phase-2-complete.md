# v4 Phase 2 — Complete

* **Branch:** `refactor/v4-phase-2-boundary-enforce`
* **Merged:** to `dev` with `--no-ff`
* **Effort:** max

## Goal

Remove every silent India fallback from promoted code. Make missing
region/timezone/currency context a structured error. Hard-block non-
India brokers from any v1 route.

## Gaps closed (from `v3_baseline_audit.md`)

* **Gap 7** — `telegram_db` per-user default `timezone="Asia/Kolkata"`.
  Now resolves the active broker's region tz at insert time; falls
  through to `"UTC"` when no broker context exists. Additive
  migration adds a `timezone_source` column for audit and backfills
  existing rows with `"default_legacy_india"` (where the value was
  `"Asia/Kolkata"`) or `"user"` (otherwise).
* **Gap 14** — v1 schemas legacy stamp. `restx_api/account_schema.py`
  now has `LEGACY_INDIA_COMPATIBILITY = True` (joining `schemas.py`
  and `data_schemas.py`).
* **Gap 15 (partial)** — frontend `LEGACY_FALLBACK_EXCHANGES`. The
  literal constant is renamed to `INDIA_LEGACY_FALLBACK_EXCHANGES`
  and is only consumed by the India-shaped fallback branch in
  `useSupportedExchanges.ts`. Phase 6 of v4 finishes the closure by
  removing the fallback entirely (capability-driven hooks).

## Invariants enforced

* **Invariant 1** — no silent India fallback. `_FALLBACK_REGION` and
  `FALLBACK_REGION_CODE` removed from `services/feature_gate_service.py`
  and `services/market_region_service.py`. `active_region_code()`
  raises `RegionResolutionError` when nothing resolves and the caller
  has not opted into the legacy India compatibility path. The
  `legacy_india_fallback=True` opt-in is the named, deprecated path
  used by `is_india_region_active()` and
  `is_feature_enabled_for_active_region()` (the explicit, named region
  gate that services-not-yet-provider-pluggable still rely on).
* **Invariant 5** — v1 hard-block for non-India brokers.
  `restx_api/_v1_lane_guard.py:enforce_india_only` runs as a
  `before_request` hook on `api_v1_bp`. Non-India brokers receive
  HTTP 410 Gone with code `v1_unavailable_for_non_india_broker`.
  India brokers and unknown-capability brokers (legacy plugin shape)
  pass through unchanged.

## New domain types

| Type | Purpose |
|---|---|
| `domain.errors.RegionResolutionError` | Raised when active region can't be resolved and legacy fallback is not opted in. |
| `domain.errors.ConfigurationError` | Raised when a required env var is missing in non-India context (e.g., `SESSION_EXPIRY_TIMEZONE`). |
| `ErrorCode.REGION_RESOLUTION_ERROR` | Stable code for the API surface. |
| `ErrorCode.CONFIGURATION_ERROR` | Stable code. |
| `ErrorCode.V1_UNAVAILABLE_FOR_NON_INDIA_BROKER` | The 410 payload for v1 hard-block. |
| `ErrorCode.LEGACY_FALLBACK_BLOCKED_FOR_NON_INDIA` | Reserved for Phase 5/6 use. |
| `ErrorCode.INSTRUMENT_AMBIGUOUS`, `INSTRUMENT_NOT_RESOLVABLE`, `PROMOTED_CAPABILITY_UNAVAILABLE`, `QUOTE_ADAPTER_NOT_REGISTERED`, `BAR_ADAPTER_NOT_REGISTERED`, `POSITION_ADAPTER_NOT_REGISTERED`, `BALANCE_ADAPTER_NOT_REGISTERED`, `SANDBOX_PROVIDER_NOT_REGISTERED`, `OPTIONS_PROVIDER_NOT_REGISTERED`, `SCREENER_PROVIDER_NOT_REGISTERED` | Reserved for later phases (Phase 5/8/9/10). |

## Behavior changes

* **`utils/session.py`** — `_session_tz()` is now fail-closed for
  non-India brokers when `SESSION_EXPIRY_TIMEZONE` is unset. India
  brokers, legacy India plugins (no explicit `supported_regions`),
  and bootstrap state (no broker session yet) all default to
  `Asia/Kolkata` so existing deployments are unaffected. Only a
  confidently-resolved non-India broker triggers `ConfigurationError`.
* **`utils/auth_utils.py`** — `tz_label` is now `tz.zone` (the actual
  IANA zone string) instead of the binary `"UTC"`/`"IST"` label that
  forced foreign-broker labels through an India-shaped lens.
* **`blueprints/master_contract_status.py`** — `/master-contract/smart-status`
  surfaces the actual configured timezone string from the broker's
  `master_contract_refresh_policy`, not `"UTC"`/`"IST"`.

## Deployment defaults

* **`docker-compose.yaml`** — `TZ=${OPENALGO_DEPLOY_TZ:-UTC}` (was
  `TZ=Asia/Kolkata`).
* **`.sample.env`** — documented `OPENALGO_DEPLOY_TZ` with examples
  for India / US / EU / UK; updated `SESSION_EXPIRY_TIMEZONE` block
  with v4 fail-closed semantics.
* **`install/install.sh`** — `check_timezone()` is region-agnostic;
  prompts the operator for an IANA timezone instead of defaulting to
  `Asia/Kolkata`.

## Frontend changes

* **`frontend/src/lib/india_legacy/legacy_fallback_exchanges.ts`** —
  exports renamed `INDIA_LEGACY_FALLBACK_EXCHANGES` (the original
  `LEGACY_FALLBACK_EXCHANGES` re-exported as a `@deprecated` alias for
  one release).
* **`frontend/src/hooks/useSupportedExchanges.ts`** — uses the new
  name. The fallback path remains gated behind the `indiaShaped`
  branch; non-India brokers without venue codes get `[]`. Phase 6
  removes the fallback entirely.

## New tests added

| File | Purpose |
|---|---|
| `tests/services/test_feature_gate_no_silent_fallback.py` | `active_region_code` raises without legacy opt-in; `is_india_region_active` and `is_feature_enabled_for_active_region` never raise; module-level `_FALLBACK_REGION` removed. |
| `tests/services/test_market_region_no_silent_fallback.py` | `FALLBACK_REGION_CODE` removed; `_legacy_india_region_for_compat()` returns `"india"`; `_fallback_region_code` prefers India when present. |
| `tests/sessions/test_session_fail_closed_non_india.py` | `_session_tz` fail-closed for non-India broker; defers to `Asia/Kolkata` for bootstrap / legacy / India broker / invalid env. |
| `tests/blueprints/test_master_contract_status_labels.py` | `get_master_contract_cutoff` returns IANA zone string; `/smart-status` surfaces the real tz. |
| `tests/contracts/test_v1_lane_blocks_non_india.py` | v1 hard-block: non-India broker → 410; India broker → pass-through; no broker → pass-through; unknown caps → pass-through. |

## Updated tests

| File | Change |
|---|---|
| `tests/services/test_feature_gate_service.py` | Replaced `test_default_active_region_is_india_when_nothing_set` with two tests: one asserting `RegionResolutionError` raises, one asserting the legacy opt-in still returns India. |
| `tests/contracts/test_v4_no_new_india_fallback.py` | Removed `xfail` marker — invariant is now enforced. |

## Migrations

* `upgrade/migrate_telegram_timezone_source.py` — additive: adds
  `timezone_source` column (nullable, default `"default_via_region"`);
  backfills existing rows to `"default_legacy_india"` or `"user"`.
  Idempotent.

## Comprehensive testing (gate 2.6)

| Step | Result |
|---|---|
| `pytest -x tests/contracts/ tests/parity/ tests/compliance/` | 108 passed, 4 xfailed (Phase 4/8/9/10 placeholders) — 8s |
| `python tests/parity/run_parity.py` | 7/7 passed |
| `pytest tests/` | 1840 passed, 7 skipped, 4 xfailed — 155s |
| `npm run lint:literals` | 253 files scanned, 0 violations |
| `npm run test -- --run` | 120 tests passed in 11 files |
| `python scripts/audit/classify_files.py --check` | 813 files, no drift |
| `python scripts/audit/route_fallback_scan.py` | 50 routes |
| `python scripts/audit/symtoken_callers.py` | 0 PROMOTED_LEAK rows |
| `python scripts/audit/canonical_vs_legacy_parity.py` | 13 pairs |

All gates pass.

## Files touched

* Modified: 17 files (services, utils, restx_api, blueprints, frontend,
  classification rules, deployment defaults, existing tests).
* Created: 7 files (`_v1_lane_guard.py`, 5 new test files,
  telegram migration script, this completion doc).

## Deferred follow-ups

* Phase 6 of v4 fully removes the `INDIA_LEGACY_FALLBACK_EXCHANGES`
  fallback (capability-driven hooks).
* Phase 9 of v4 retires the `is_india_region_active()` callsites in
  the option services as they migrate to provider-pluggable dispatch.
* `services/flow_executor_service.py` per-node `"NSE"`/`"MIS"` defaults
  (gap 3 partial) — Phase 6 wires region-driven defaults from
  `/api/v2/regions/<region>/flow_defaults`.
