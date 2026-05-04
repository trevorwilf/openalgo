# v7 — Market-agnostic refactor status

Continuation of Expert 3's 33-task backlog (T-01..T-33) on top of
the v6-FINAL baseline. v7 closes the promoted-lane IST cleanup,
default-fallback elimination, broker provenance in persistence,
the audit/closing-invariant infrastructure, real EU/UK options +
US production-readiness plugins, region-plugin-driven sandbox
capital, and Delta Exchange's crypto-region migration.

## v7 phase delivery

| Phase | Status | Tasks landed | Closing invariant |
|---|---|---|---|
| 1 | ✅ complete | T-01, T-02, T-03 | (precursor v7-B + v7-C) |
| 2 | ✅ complete | T-04, T-05, T-07, T-08, T-10, T-11 | (precursor v7-D) |
| 3 | ✅ complete | T-09, T-14, T-31, T-32 | (precursor v7-E) |
| 3-bis | ✅ partial | T-19 (full), T-20 (paytm only) | — |
| 3-ter | ✅ complete | T-12, T-13, T-18 | — |
| 4 | ✅ complete | T-17, T-33 | (v7 closing test) |
| 4-bis | ✅ complete | T-06, T-15 | v7-F |
| 4-bis-2 | ✅ complete | SymToken UNIQUE constraint | — |
| 4-bis-3 | ✅ complete | T-16 | — |
| 5 | ✅ partial | T-25 (scaffolds; pages deferred) | — |
| 6 | ✅ complete | T-21, T-22 (sandbox enabled) | — |
| 6-bis | ✅ complete | T-23, T-24 (real EU/UK options) | — |
| 7-bis | ✅ complete | T-26, T-27, T-28, T-29 | — |
| 8 | ✅ complete | T-30 + Delta migration | — |

## v7 closing invariants — all 6 GREEN

| # | Invariant | Status |
|---|---|---|
| v7-A | No promoted module imports from `legacy_v1/` outside documented shims | ✅ |
| v7-B | No `Asia/Kolkata` literal in promoted blueprints | ✅ |
| v7-C | 4 promoted DB helpers stamp UTC | ✅ |
| v7-D | No silent `MIS`/`XNAS` defaults in v1_compat_bridge | ✅ |
| v7-E | `master_contract_refresh_policy` mandatory for non-legacy plugins | ✅ |
| v7-F | SymToken includes `broker_code` + `instrument_id` | ✅ |

## Audit infrastructure (T-31, T-32)

* `scripts/audit/india_literal_scan_backend.py` — backend mirror
  of frontend literal scanner. **327 files scanned, 0 violations.**
* `scripts/audit/broker_capability_drift_scan.py` — declared-vs-
  exercised mismatch detector. **37 plugins audited, 0 drift.**

## Capability schema additions (v7)

`domain/capabilities.BrokerCapabilities` gained these optional
fields in v7 (additive only; legacy plugins don't change):

* `default_venue_code: str | None` (T-04)
* `default_product_code: str | None` (T-04)

The strict-mode plugin loader allowlist also recognizes these
optional plugin.json keys post-v7:

* `streaming_transports`, `supports_account_hashes`,
  `supports_subaccounts`, `requires_market_price_protection`,
  `requires_slm_to_sl_conversion`, `requires_v1_compat`

## Region plugin schema additions

All 5 region plugins (india/us/eu/uk/crypto) now declare:

* `product_vocabulary` (per-asset-class + ALL)
* `price_type_vocabulary`
* `legacy_compat_shim.valid_exchanges`

T-12 closes by routing promoted-lane callers through
`services.market_region_service.get_allowed_*_for_active_region`
helpers instead of `utils.constants` legacy India shim.

The India region plugin also gained:

* `metadata.sandbox_initial_funds` (T-16) — the v2 sandbox
  provider's initial funds value (₹10L preserved).
* `metadata.sandbox_starting_capital_default` slot — read by
  the legacy fund_manager when no operator config is present.

## Persistence broker provenance (T-06, T-15, Phase 4-bis-2)

* `SymToken.broker_code` (NULL initially, indexed)
* `SymToken.instrument_id` (NULL initially, indexed; UUID4 per row
  after backfill)
* `UNIQUE (broker_code, symbol, exchange)` — Phase 4-bis-2;
  treats NULLs as distinct so pre-backfill rows don't collide.
* `historify.market_data.broker_code` (NULL initially)

Migration script: `upgrade/migrate_symtoken_broker_provenance.py`
backfills `broker_code` from `BROKER_API_KEY` / `DEFAULT_BROKER`
env resolution, idempotent + reversible.

## Crypto region (T-30)

`market_regions/crypto/` plugin loads in the now-five-region
matrix. Borderless (no `country_codes`), 24/7 sessions
(`ALL_DAY`), USDT primary quote currency.

Delta Exchange flipped `supported_regions: ["india"] → ["crypto"]`
with full strict-mode metadata declarations. The dispatcher now
resolves Delta sessions through the crypto region plugin.

## Real options providers (T-23, T-24)

EU and UK options providers replaced the
`OPTION_CHAIN_DISABLED_IN_REGION` stubs with:

* OCC-style 21-character symbol parsing.
* Currency tagging (EUR / GBP) and venue codes (XEUR / IFEU).
* Third-Friday monthly expiry calculation.
* Greeks / IV computation via `domain.options_math` (shared with
  the US provider).
* Non-empty `supported_strategies` set.

`feature_flags.option_chain_enabled` stays false on the EU and UK
plugins — providers exist but the dispatcher doesn't route by
default. Operators flip the flag to enable.

## US broker plugins (T-27, T-28, T-29)

* **Alpaca**: full capability surface (auth_modes,
  streaming_transports, all the requires_* and supports_*
  flags). Production-ready capability declarations.
* **Schwab**: new `broker/schwab/` directory with full plugin.json.
  Real API code deferred to v8 (blocked on official API access).
* **Webull**: new `broker/webull/` directory with full plugin.json.
  Real API code deferred to v8.

The underscore-prefixed mock plugins (`_mock_schwab_like`,
`_mock_webull_like`) remain as the framework-test fixtures.

Plugin loader status: **37 plugins loaded** (was 35 before v7's
Schwab + Webull additions; 35 → 37 + Delta unblocked).

## Frontend region siblings (T-25 scaffolds)

`frontend/src/{us,eu,uk}/` directories created with `index.ts`
entry barrels exporting `REGION_CODE`. Each ships a README
documenting structure (mirrors `india_legacy/`) and mounting
conventions. Page-level components deferred — the structural
deliverable is in.

## Sandbox capital region-driven (T-16)

* India region plugin metadata now declares
  `sandbox_initial_funds = "1000000.00"` (₹10L) for the v2
  provider and (via fallback) `sandbox_starting_capital_default`
  for the legacy fund_manager.
* `services/sandbox/providers/india/__init__.py` reads from the
  region plugin instead of hard-coding the literal.
* `market_regions/india/legacy_v1/sandbox/fund_manager.py` reads
  the legacy ₹1Cr default through the same indirection.

India parity preserved (existing installs see no change).
Operators wanting different defaults edit one place — the region
plugin metadata — instead of editing Python.

## Deferred tasks

| Task | Status | Reason |
|---|---|---|
| T-20 (groww/nubra) | partial deferred | groww has 30+ entangled IST refs in API parsing; nubra has 3 hardcoded IST→UTC offsets. Needs focused pass — broker's API itself emits IST timestamps for India market data. |
| T-25 follow-up | deferred | Real frontend pages (~393 net-new TSX/TS files). The scaffolds + REGION_CODE export ship today; per-page expansion follows demand. |
| Schwab/Webull production | deferred to v8 | API access not yet granted. Plugin scaffolds + capability surface ship today. |
| `symtoken_v1` view | deferred | Caller updates in services/symbol_service.py + services/instruments_service.py needed before the v1 lane can read through the view. |
| India CRYPTO removal | parity-pinned | The exact "Must be one of: NSE, NFO, ..., CRYPTO" error string in `tests/parity/baseline/parity_place_order_validation.json` pins the current vocabulary. Coordinated baseline regen needed. |

## Final test gate counts

| Step | Result |
|---|---|
| `uv run python tests/parity/run_parity.py` | **41/41** v2 (bit-identical) |
| `uv run python tests/parity/run_parity.py --lane v1` | **11/11** v1 (bit-identical) |
| `uv run pytest tests/contracts/test_v7_closing_invariants.py` | **6/6** |
| `uv run python scripts/audit/india_literal_scan_backend.py` | exit 0, 327 files |
| `uv run python scripts/audit/broker_capability_drift_scan.py` | exit 0, **37 plugins** |
| `uv run python scripts/audit/symtoken_callers.py` | 0 PROMOTED_LEAK |

## Net new tests added in v7

~70 new test files / parametrized cases across:

- Contracts: `test_v7_a..f_closing_invariants.py`, `test_session_tz_fail_closed`, `test_v2_no_india_tz_in_payloads`, `test_master_contract_refresh_policy_mandatory`, `test_frontend_region_siblings_present`
- Services: `test_v1_compat_bridge_no_india_defaults`, `test_promoted_mpp_routes_by_region`
- Blueprints: `test_active_render_tz_name`
- Migrations: `test_telegram_tz_no_default`, `test_seed_venue_schedule_multi_region`
- Region loader: `test_crypto_region_loads`, `test_region_vocabularies`
- Sandbox: `test_eu_uk_providers_enabled`, `test_starting_capital_region_driven`
- Options: `test_eu_uk_options_providers`
- Restx_api v2: `test_holidays_region_dispatch`
- Audit: `test_india_literal_scan_backend`, `test_broker_capability_drift_scan`
- Instruments_repo: `test_symtoken_broker_code_columns`
- Historify: `test_historify_broker_code_column`
- Instrument sync: `test_us_adapter_base`
- Broker: `test_deltaexchange_supported_regions`, `test_us_broker_plugins_complete`

## Commits this session

**36 commits**, **18 phase merges to `dev`** (each `--no-ff`).

## What v8 should consider

* Real Schwab + Webull API integration (when access lands).
* Real Alpaca production verification (place order, modify,
  cancel, stream — against live paper API).
* T-25 follow-up: page-level frontend components.
* T-20 follow-up: groww + nubra IST refs.
* `symtoken_v1` view + caller updates in `symbol_service.py` /
  `instruments_service.py`.
* India CRYPTO removal coordinated with parity baseline regen.
* Phase 4-bis-2 follow-up: cross-broker query support in the v2
  symbol service (filter by broker_code).
* Real EU/UK options chain market-data adapters.
* APAC ex-India / LATAM region plugins.
