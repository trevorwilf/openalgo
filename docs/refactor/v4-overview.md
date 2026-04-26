# Market-Agnostic Refactor v4 — Overview

v4 is the framework-readiness pass. It closes the 17 confirmed v3 gaps,
generalizes Sandbox / Options / Screener into provider-pluggable
contracts (with India + US provider implementations), hard-blocks v1 for
non-India brokers, and stamps every promoted code path with explicit
fail-closed behavior.

**Authoritative source:** `openalgo_market_agnostic_v4_claude_code_prompt.md`
in the repo root. Two independent expert reviews informed the prompt;
where the experts disagreed, the prompt picks the stricter path.

**Out of scope:** real Schwab API code, real Webull API code, real OAuth
flows, real broker network calls. The mock `_mock_schwab_like` and
`_mock_webull_like` plugins prove the framework can host them.

---

## v4 invariants

These are non-negotiable. Each is enforced by a contract test in
`tests/contracts/`. The numbers below match Section 1 of the v4 prompt.

| # | Invariant | Enforced by |
|---|---|---|
| 1 | No new `_FALLBACK_REGION = "india"` style fallbacks in promoted code | `test_v4_no_new_india_fallback.py` |
| 2 | No new `Asia/Kolkata` literal in PROMOTED_CORE or non-India broker plugins | `test_lane_isolation.py` (literal scanner) |
| 3 | No new India-shaped literal (NSE/NFO/MIS/CNC/NRML/CE/PE/INR/₹/lakh/crore/DDMMMYY/NIFTY/BANKNIFTY/SENSEX) in PROMOTED_CORE or non-India broker plugins | `test_lane_isolation.py` |
| 4 | No new code may import VALID_EXCHANGES / VALID_PRODUCT_TYPES / VALID_PRICE_TYPES from `utils/constants.py` | `test_lane_isolation.py` |
| 5 | Non-India brokers must not route through the legacy India services (place_order_service, basket_order_service, margin_service, v1 schemas, quotes_service legacy mode, history_service legacy mode, India option services as legacy implementations, market_calendar_db, database.symbol, database.token_db_enhanced) | `test_v4_no_legacy_imports_from_promoted.py` (static), `test_promoted_imports_runtime.py` (runtime), `test_v1_lane_blocks_non_india.py` (request-time) |
| 6 | Promoted plugin schema is strict — unknown operational fields are validation errors, missing required promoted fields block activation | `test_v4_promoted_plugin_strict_mode.py` |
| 7 | Sandbox / Options / Screener are provider-pluggable; UI exposes a feature only when an active broker's region has a registered provider | `test_v4_advanced_feature_provider_contracts.py` |
| 8 | Real Schwab and Webull broker code is out of scope for v4 | enforced by review |
| 9 | Additive migrations only — no `DROP COLUMN`, no `DROP TABLE` | enforced by review |
| 10 | Indian broker behavior preserved bit-identically — `tests/parity/run_parity.py` passes at every phase boundary | parity harness |
| 11 | Capability-driven, not heuristic — no `if broker == "..."` or `if region == "india"` outside `services.feature_gate_service.is_india_region_active()` | `test_lane_isolation.py` + `test_classification_invariants.py` |
| 12 | `SymToken` is read-only and India-only — zero PROMOTED_LEAK rows in `docs/refactor/symtoken_callers.md` | `test_symtoken_callers_zero_leaks.py` |

---

## Phases

| Phase | Goal | Closes v3 gaps | Status |
|---|---|---|---|
| 1 | Baseline refresh, classification re-run, v4 governance | sets up enforcement | in progress |
| 2 | Boundary enforcement + v1 hard-block for non-India | 7, 14, 15 (partial) | pending |
| 3 | Region/venue/calendar/instrument data promotion | 11, 16 | pending |
| 4 | Broker plugin strict-mode + capability hardening | invariant 6 | pending |
| 5 | v2 quotes/bars/positions/balances fail-closed completion | 1, 2, 10 | pending |
| 6 | Frontend capability-driven UI cleanup (66 files) | 3, 8, 9, 15 (full) | pending |
| 7 | Historify + Strategy scheduler venue-tz aware | 6, 13 (strategy portion) | pending |
| 8 | Sandbox provider-pluggable redesign + India + US providers | invariant 7 (sandbox) | pending |
| 9 | Options provider-pluggable redesign + India + US providers | 4, 5 (provider) | pending |
| 10 | Screener provider abstraction (Chartink as India provider) | 13 (chartink portion) | pending |
| 11 | Mock Schwab/Webull end-to-end framework readiness | 12 | pending |
| 12 | Final verification, doc consolidation, v4 closing audit | doc alignment | pending |

Each phase has its own completion document at `docs/refactor/v4-phase-<N>-complete.md`
written at merge time.

---

## What v5 should consider

(Filled in by Phase 12 once v4 closes.)

* Real Schwab plugin work (blocked on official API validation).
* Real Webull plugin work (blocked on official API validation).
* EU / UK pilot real-broker plugin.
* Deprecation of legacy India services after one full release of held parity
  (see `deprecation-schedule.md`).

---

## Authoritative cross-references

* `docs/refactor/v3_baseline_audit.md` — gap tracker; updated continuously.
* `docs/refactor/file_classification.md` — PROMOTED_CORE / LEGACY_INDIA / REGION_PLUGIN / BROKER_PLUGIN / COMPATIBILITY_SHIM bucket of every Python source file.
* `docs/refactor/route_fallback_inventory.md` — per-route v1/v2 lane disposition.
* `docs/refactor/symtoken_callers.md` — SymToken caller audit (zero PROMOTED_LEAK rows is the contract).
* `docs/refactor/canonical_legacy_parity_report.md` — canonical-vs-legacy parity yardstick.
* `docs/refactor/broker_compliance_matrix.md` — per-broker compliance results.
* `docs/refactor/schwab_readiness.md` / `webull_readiness.md` — framework-readiness evidence packages.
* `docs/adr/0001-*.md` through `0028-*.md` — accepted ADRs.
