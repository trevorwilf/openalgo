# v7 — Market-agnostic refactor status

Continuation of Expert 3's 33-task backlog (T-01..T-33). v6 closed
the four-region matrix + India translator activation; v7 closes
the promoted-lane IST cleanup, default-fallback elimination,
broker provenance in persistence, and ships the audit/closing-
invariant infrastructure.

## v7 phase delivery

| Phase | Status | Tasks landed | Closing invariant |
|---|---|---|---|
| 1 | ✅ complete | T-01, T-02, T-03 | (precursor v7-B + v7-C) |
| 2 | ✅ complete | T-04, T-05, T-07, T-08, T-10, T-11 | (precursor v7-D) |
| 3 | ✅ complete | T-09, T-14, T-31, T-32 | (precursor v7-E) |
| 3-bis | ✅ partial | T-19 (full), T-20 (paytm) | — |
| 3-ter | ✅ complete | T-12, T-13, T-18 | — |
| 4 | ✅ complete | T-17, T-33 | (v7 closing test) |
| 4-bis | ✅ complete | T-06, T-15 | v7-F |
| 5 | ⏸ deferred | T-25 | — |
| 6 | ✅ partial | T-21, T-22 | — |
| 7 | ⏸ deferred | T-26..T-29 | — |
| 8 | ✅ partial | T-30 | — |

## v7 closing invariants — all 6 GREEN

| # | Invariant | Test |
|---|---|---|
| v7-A | No promoted module imports from `legacy_v1/` outside documented shims | `test_v7_invariant_v7_a_no_promoted_legacy_v1_imports` |
| v7-B | No `Asia/Kolkata` literal in promoted blueprints | `test_v7_invariant_v7_b_no_kolkata_in_promoted_blueprints` |
| v7-C | 4 promoted DB helpers stamp UTC | `test_v7_invariant_v7_c_promoted_db_helpers_utc_stamp` |
| v7-D | No silent `MIS`/`XNAS` defaults in v1_compat_bridge | `test_v7_invariant_v7_d_no_silent_india_defaults_in_v1_bridge` |
| v7-E | `master_contract_refresh_policy` mandatory for non-legacy plugins | `test_v7_invariant_v7_e_refresh_policy_mandatory_for_non_legacy` |
| v7-F | SymToken includes `broker_code` + `instrument_id` | `test_v7_invariant_v7_f_symtoken_includes_broker_code` |

All 6 pass. No xfails.

## Audit infrastructure (T-31, T-32)

* `scripts/audit/india_literal_scan_backend.py` — backend mirror
  of frontend literal scanner. 327 files scanned, 0 violations.
  Allowlist documents every legacy India broker plugin, the
  sandbox providers (T-16 follow-up), and the v1_compat_bridge
  alias map.
* `scripts/audit/broker_capability_drift_scan.py` — declared-vs-
  exercised capability mismatch detector. 35 plugins audited,
  0 drift.

Both join the existing `uv run python scripts/audit/*` step in
the comprehensive testing block.

## Capability schema additions

`domain/capabilities.BrokerCapabilities` gained two optional
fields in v7:

* `default_venue_code: str | None` — broker's default venue for
  v1 UI display. v1 compat bridge reads this (T-04) and India
  broker `mapping/order_data.py` files read this (T-19).
* `default_product_code: str | None` — broker's default product
  for v1 UI display.

Strict-mode plugin loader (ADR 0025) recognizes both as additive
optional fields.

## Region plugin schema additions

All 5 region plugins now declare:

* `product_vocabulary` (per-asset-class + ALL)
* `price_type_vocabulary`
* `legacy_compat_shim.valid_exchanges`

T-12 closes by routing promoted-lane callers through
`services.market_region_service.get_allowed_*_for_active_region`
helpers instead of `utils.constants` legacy India shim.

## SymToken / Historify broker provenance (T-06, T-15)

Both tables now carry:

* `broker_code VARCHAR NULL` (indexed)
* `instrument_id VARCHAR NULL` (indexed; SymToken only — historify
  already had it from a prior phase)

Both columns nullable initially so existing rows survive without
migration. `upgrade/migrate_symtoken_broker_provenance.py`
backfills `broker_code` from `BROKER_API_KEY` /
`DEFAULT_BROKER` env resolution and assigns UUID4 `instrument_id`
per row. Idempotent + reversible (downgrade drops both columns).

## Crypto region (T-30)

`market_regions/crypto/` plugin loads in the now-five-region
matrix. Borderless (no `country_codes`), 24/7 sessions
(`ALL_DAY`), USDT primary quote currency.

## Deferred tasks

| Task | Reason | Notes |
|---|---|---|
| T-16 | Parity baseline pins `_INITIAL_FUNDS = ₹10L` | Coordinated update of `tests/parity/baseline/parity_sandbox_india.json` required alongside the literal removal. |
| T-20 (groww/nubra) | groww has 30+ entangled IST refs in API parsing | Needs focused pass; broker's API itself emits IST timestamps for India market data. |
| T-23, T-24 | Real EU/UK options grammar (Eurex/Euronext/ICE) | Needs region-specialist domain knowledge. The existing stubs route the dispatcher correctly and surface `option_chain_disabled_in_region`. |
| T-25 | Frontend siblings under `frontend/src/{us,eu,uk}/` | `india_legacy/` is 131 files — building three siblings is ~393 net-new TSX/TS files. |
| T-26 | Master-contract sync template generalization | Mostly cosmetic; closes alongside T-27/28/29. |
| T-27 | Real Alpaca production hardening | Capability declarations already substantively complete (T-04 added `default_venue_code`/`default_product_code`; T-09 confirmed `master_contract_refresh_policy`). Production hardening = real-API contract verification. |
| T-28 | Real Schwab plugin | **Blocked** on official API access per stakeholder notes. |
| T-29 | Real Webull plugin | **Blocked** on official API access. |
| Phase 4-bis-2 | SymToken `(broker_code, symbol, exchange)` UNIQUE constraint + `symtoken_v1` view | Needs operator coordination; requires migration backfill before constraint can be added without violations. |
| Phase 8 follow-up | Delta Exchange `supported_regions: ["crypto"]` flip | Capability inference change — coordinated with parity baseline + region-feature gates. |

## Final test gate counts

| Step | Result |
|---|---|
| `uv run python tests/parity/run_parity.py` | **41/41** v2 (bit-identical) |
| `uv run python tests/parity/run_parity.py --lane v1` | **11/11** v1 (bit-identical) |
| `uv run pytest tests/contracts/test_v7_closing_invariants.py` | **6/6** (was 5 + xfail in Phase 4 partial) |
| `uv run pytest tests/contracts/test_v{4,5,6}_closing_invariants.py` | unchanged from v6-FINAL |
| `uv run python scripts/audit/india_literal_scan_backend.py` | exit 0, 327 files |
| `uv run python scripts/audit/broker_capability_drift_scan.py` | exit 0, 35 plugins |

## Net new tests added in v7

~50 across:
- `tests/contracts/test_v7_*.py` (4 files)
- `tests/contracts/test_session_tz_fail_closed.py`
- `tests/contracts/test_v2_no_india_tz_in_payloads.py`
- `tests/contracts/test_master_contract_refresh_policy_mandatory.py`
- `tests/services/test_v1_compat_bridge_no_india_defaults.py`
- `tests/services/test_promoted_mpp_routes_by_region.py`
- `tests/blueprints/test_active_render_tz_name.py`
- `tests/migrations/test_telegram_tz_no_default.py`
- `tests/migrations/test_seed_venue_schedule_multi_region.py`
- `tests/region_loader/test_crypto_region_loads.py`
- `tests/region_loader/test_region_vocabularies.py`
- `tests/sandbox/test_eu_uk_providers_enabled.py`
- `tests/restx_api/v2/test_holidays_region_dispatch.py`
- `tests/audit/test_india_literal_scan_backend.py`
- `tests/audit/test_broker_capability_drift_scan.py`
- `tests/instruments_repo/test_symtoken_broker_code_columns.py`
- `tests/historify/test_historify_broker_code_column.py`

## What v8 should consider

* Real Schwab + Webull plugins (when API access lands).
* Real Alpaca production verification.
* T-25 — frontend region siblings (US/EU/UK).
* T-23 / T-24 — real EU/UK options providers.
* Phase 4-bis-2 — SymToken UNIQUE constraint + view + caller updates.
* Phase 8 follow-up — Delta Exchange supported_regions migration.
* T-16 — sandbox capital reconciliation with coordinated parity update.
