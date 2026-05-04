# v7 — FINAL CLOSING REPORT

> Authoritative state-of-v7 doc. Supersedes `v7-status.md` which
> was the in-progress tracker.

## v7 verdict

**v7 is COMPLETE.** Every task in Expert 3's 33-task backlog
(T-01..T-33) has shipped, plus follow-up sub-phases that closed
items the original prompt deferred. India parity is bit-identical
on every commit; v7-A through v7-F closing invariants are all
green with no xfails.

## Phase delivery summary (final)

| Phase | Status | Tasks | Closing doc / commit |
|---|---|---|---|
| 1 | ✅ complete | T-01, T-02, T-03 | `d5493ec5` |
| 2 | ✅ complete | T-04, T-05, T-07, T-08, T-10, T-11 | `7a480940` |
| 3 | ✅ complete | T-09, T-14, T-31, T-32 | `bd3acc18` |
| 3-bis | ✅ complete | T-19 (10 brokers), T-20 (paytm) | `6d2c2b02` |
| 3-bis-2 | ✅ complete | T-20 (nubra) | `phase-3-bis-2` |
| 3-bis-3 | ✅ complete | T-20 (groww) | `phase-3-bis-3` |
| 3-ter | ✅ complete | T-12, T-13, T-18 | `fdbe3f5f` |
| 4 | ✅ complete | T-17, T-33 | `5a89e42f` |
| 4-bis | ✅ complete | T-06, T-15 | `0a778ce4` |
| 4-bis-2 | ✅ complete | SymToken UNIQUE constraint | `phase-4-bis-2` |
| 4-bis-3 | ✅ complete | T-16 region-plugin-driven sandbox capital | `phase-4-bis-3` |
| 4-bis-4 | ✅ complete | symtoken_v1 view in migration | `phase-4-bis-4` |
| 4-bis-5 | ✅ complete | cross-broker symbol query helper | `phase-4-bis-5` |
| 4-bis-6 | ✅ complete | SymTokenV1Read ORM model | `phase-4-bis-6` |
| 5 | ✅ complete | T-25 (US/EU/UK scaffolds + RegionContent) | `88aa6f28`, `phase-5-region-router` |
| 6 | ✅ complete | T-21, T-22 (sandbox enabled) | `2578eace` |
| 6-bis | ✅ complete | T-23, T-24 (real options providers) | `c4d44fcc` |
| 7-bis | ✅ complete | T-26, T-27, T-28, T-29 | `b29a773c`, `phase-7-master-contract-sync` |
| 8 | ✅ complete | T-30 + Delta migration + India CRYPTO removal | `ab0b9951`, `92db9877`, `phase-8-india-crypto-removal` |

## v7 closing invariants — all 6 GREEN

| # | Invariant | Test |
|---|---|---|
| v7-A | No promoted module imports from `legacy_v1/` outside documented shims | `test_v7_invariant_v7_a_no_promoted_legacy_v1_imports` |
| v7-B | No `Asia/Kolkata` literal in promoted blueprints | `test_v7_invariant_v7_b_no_kolkata_in_promoted_blueprints` |
| v7-C | 4 promoted DB helpers stamp UTC | `test_v7_invariant_v7_c_promoted_db_helpers_utc_stamp` |
| v7-D | No silent `MIS`/`XNAS` defaults in v1_compat_bridge | `test_v7_invariant_v7_d_no_silent_india_defaults_in_v1_bridge` |
| v7-E | `master_contract_refresh_policy` mandatory for non-legacy plugins | `test_v7_invariant_v7_e_refresh_policy_mandatory_for_non_legacy` |
| v7-F | SymToken includes `broker_code` + `instrument_id` | `test_v7_invariant_v7_f_symtoken_includes_broker_code` |

## Final test gate counts

| Step | Result |
|---|---|
| `uv run python tests/parity/run_parity.py --lane v1` | **11/11** v1 (bit-identical or regenerated for T-30 CRYPTO removal) |
| `uv run python tests/parity/run_parity.py --lane v2` | **41/41** v2 (bit-identical) |
| `uv run pytest tests/contracts/test_v7_closing_invariants.py` | **6/6** (no xfails) |
| `uv run pytest tests/contracts/test_v{4,5,6,7}_closing_invariants.py` | **45 passed** |
| `uv run python scripts/audit/india_literal_scan_backend.py` | exit 0, **330 files** scanned |
| `uv run python scripts/audit/broker_capability_drift_scan.py` | exit 0, **37 plugins** audited |
| `uv run python scripts/audit/classify_files.py --check` | OK, **1010 files** classified, no drift |
| `uv run python scripts/audit/symtoken_callers.py` | **0 PROMOTED_LEAK** rows |
| `uv run python scripts/audit/canonical_vs_legacy_parity.py` | exit 0 |
| `uv run python scripts/audit/route_fallback_scan.py` | exit 0 |
| Full Playwright live suite | **148/148 passed** (most recent clean run before final shutdown) |
| `uv run python tools/api_surface_sweep.py` | **29/29 passed** including Alpaca direct cross-check |

## v7 by-the-numbers

| Metric | Count |
|---|---|
| Phases shipped (incl. bis-phases) | **18** (1, 2, 3, 3-bis, 3-bis-2, 3-bis-3, 3-ter, 4, 4-bis, 4-bis-2, 4-bis-3, 4-bis-4, 4-bis-5, 4-bis-6, 5, 6, 6-bis, 7-bis, 8) |
| Phase merges to dev (`--no-ff`) | **20+** |
| Total commits this v7 cycle | ~58 |
| Net new tests added in v7 | **~80** across 18+ test files |
| ADRs added | 0 (the prompt didn't require new ADRs; v8 will add ADR 0032) |
| New region plugins | 1 (`market_regions/crypto/`) |
| New broker plugins | 2 (`broker/schwab/`, `broker/webull/`) |
| Frontend siblings created | 3 scaffolds (`us/`, `eu/`, `uk/`) + `RegionContent` router |
| New audit scripts | 2 (`india_literal_scan_backend.py`, `broker_capability_drift_scan.py`) |
| Plugins now loaded | **37** (was 35 at v6 close; +Schwab, +Webull, +Delta-on-crypto migration unblocking it) |
| Region plugins now loaded | **5** (india, us, eu, uk, crypto — was 4) |

## Capability schema additions in v7

`domain/capabilities.BrokerCapabilities` gained:

* `default_venue_code: str | None` (T-04) — broker's default venue for v1 UI display
* `default_product_code: str | None` (T-04) — broker's default product code

The plugin loader strict-mode allowlist also recognizes these
optional plugin.json keys post-v7:

* `streaming_transports`, `supports_account_hashes`,
  `supports_subaccounts`, `requires_market_price_protection`,
  `requires_slm_to_sl_conversion`, `requires_v1_compat`,
  `default_venue_code`, `default_product_code`

## Region plugin schema additions

All 5 region plugins (india/us/eu/uk/crypto) now declare:

* `product_vocabulary` (per-asset-class + ALL)
* `price_type_vocabulary`
* `legacy_compat_shim.valid_exchanges`

The India region plugin also gained:

* `metadata.sandbox_initial_funds = "1000000.00"` (T-16)
* `metadata.sandbox_starting_capital_default` slot (T-16)
* `metadata.flow_defaults.products = ["MIS", "CNC", "NRML"]`

## Persistence broker provenance (T-06, T-15, Phase 4-bis-2/4)

* `SymToken.broker_code` (NULL initially, indexed)
* `SymToken.instrument_id` (NULL initially, indexed; UUID4 after backfill)
* `UNIQUE (broker_code, symbol, exchange)` — Phase 4-bis-2
* `historify.market_data.broker_code` (NULL initially)
* `symtoken_v1` SQL view that hides T-06 columns from external consumers
* `SymTokenV1Read` ORM model mapping over the view
* `services.symbol_service.get_symbol_info_for_broker(...)` — broker-aware lookup

Migration script: `upgrade/migrate_symtoken_broker_provenance.py`
backfills `broker_code` from `BROKER_API_KEY` / `DEFAULT_BROKER`
env resolution, idempotent + reversible.

## Crypto region (T-30)

`market_regions/crypto/` plugin loads in the now-five-region
matrix. Borderless (no `country_codes`), 24/7 sessions
(`ALL_DAY`), USDT primary quote currency.

Delta Exchange migrated from `supported_regions: ["india"]` to
`["crypto"]` with full strict-mode metadata declarations. India's
`legacy_compat_shim.valid_exchanges` no longer includes `"CRYPTO"`
— 3 parity baselines (parity_quote, parity_history,
parity_place_order_validation) regenerated to drop CRYPTO from
the valid-exchange error string.

## Real options providers (T-23, T-24)

EU and UK options providers ship with:

* OCC-style 21-character symbol parsing
* Currency tagging (EUR / GBP) and venue codes (XEUR / IFEU)
* Third-Friday monthly expiry calculation
* Greeks / IV via `domain.options_math` (shared with US provider)
* Non-empty `supported_strategies` set

`feature_flags.option_chain_enabled` stays false on the EU/UK
plugins — providers exist; operators flip the flag to enable.

## US broker plugin readiness (T-27, T-28, T-29)

* **Alpaca** — full capability surface (auth_modes,
  streaming_transports, all the requires_* / supports_* flags).
  Production-ready capability declarations.
* **`broker/schwab/`** — real plugin scaffold with full
  capability surface; real API code deferred to v8.
* **`broker/webull/`** — real plugin scaffold with full
  capability surface; real API code deferred to v8.

The underscore-prefixed `_mock_schwab_like` / `_mock_webull_like`
plugins remain as the framework-test fixtures.

## What v8 should consider

* Real Schwab + Webull API integration (when access lands)
* Real Alpaca production verification (place order, modify,
  cancel, stream — against live paper API)
* T-25 follow-up: full page-level frontend US/EU/UK siblings
* Real EU / UK options chain market-data adapters
* APAC ex-India / LATAM region plugins
* OpenTelemetry / Prometheus metrics backend upgrade
* `/api/v1/*` removal coordinated with operator sunset
* Multi-broker-per-instance deployment model
* Active migration of v1-lane callers to `SymTokenV1Read` (the
  read-only view-mapped model exists; callers still query
  `SymToken` directly)
* Page-level applications of `RegionContent` (the component
  exists; pages opt in)

## What is genuinely OUT of v7 scope

* Real-API contract verification for Schwab / Webull (blocked on
  official API access)
* Real EU / UK pilot broker plugins (no broker named per
  stakeholder)
* Multi-broker-per-instance deployment (ADR 0001 single-tenant
  locked)
* Page-by-page frontend expansion (~393 net-new TSX/TS files for
  full US/EU/UK feature parity)
