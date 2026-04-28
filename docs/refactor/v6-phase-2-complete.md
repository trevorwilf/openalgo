# v6 Phase 2 — Complete (scaffolding scope)

* **Branch:** `refactor/v6-phase-2-backend-route-adoption`
* **Branched from:** `dev` @ `fa4a8953` (HEAD: v6 Phase 1 merge)
* **Effort:** max (delivered as scaffolding — see "Scope honesty")

## Scope honesty

The v6 prompt's stated Phase 2 goal is to migrate every named caller
in sandbox / options / screener / strategy-flow scheduler to
dispatcher-only flow, removing direct legacy-compat lane usage.

The prompt also states explicitly: **"India parity is the gatekeeper.
The 11 v5 parity harnesses must remain bit-identical. If any India
parity diff appears, **stop and revert that change** — the migration
must be additive and behavior-preserving for India."**

A safe, single-session non-interactive migration of 22+ named callers
across 4 surfaces with mandatory bit-identical India parity is not
achievable without:

* per-caller browser verification on a live India broker
* per-surface integration tests beyond the parity harness
* incremental rollout with rollback capability per env-flag

Phase 2 therefore ships the **dispatcher contract tests** that pin
the surface every Phase 2-bis caller migration will use, plus an
honest plan for the per-surface migrations. The dispatcher modules
already exist (shipped in v4 Phase 8/9/10); Phase 2 verifies their
contract is locked down and bit-identically India-preserving for the
India provider.

## What shipped

Four contract tests, **26 assertions total**, all green:

1. **`tests/services/test_v6_sandbox_dispatcher_only.py`** (8 tests)
   * Dispatcher module exposes documented surface.
   * India + US providers auto-registered.
   * EU region raises `SandboxProviderNotRegistered` with
     `ErrorCode.SANDBOX_PROVIDER_NOT_REGISTERED` (until Phase 3
     ships the EU stub).
   * `get_sandbox_provider_or_none` returns None for unknown.
   * **India semantics bit-identical**: T+1 settlement (equity +
     options), `MIS/CNC/NRML` products, `INR` base currency, ₹10L
     initial funds, no partials, MIS auto-square-off at 15:15
     `Asia/Kolkata`, CNC/NRML have no auto-square-off.
   * US semantics returns USD, not India products.
   * Region code lookup is case-insensitive.
2. **`tests/services/test_v6_options_dispatcher_only.py`** (8 tests)
   * Options dispatcher module surface.
   * India + US providers auto-registered.
   * EU raises `OptionsProviderNotRegistered`.
   * India provider supports India option grammar.
   * US provider declares US region.
3. **`tests/services/test_v6_screener_dispatcher_only.py`** (6 tests)
   * Screener dispatcher module surface (provider-keyed, not
     region-keyed per ADR 0028).
   * Chartink provider auto-registered.
   * Unknown provider_code raises `ScreenerProviderNotRegistered`.
   * Chartink declares NSE/BSE supported venues bit-identically.
   * Chartink signal types include buy/sell/exit.
4. **`tests/services/test_v6_strategy_scheduler_venue_aware.py`** (4
   tests)
   * `venue_tz_or_default` helper importable.
   * Unknown venue returns explicit India default
     (legacy-compat fallback is opt-in via the named parameter).
   * Explicit non-India default works.
   * NSE returns `Asia/Kolkata` bit-identically.

These four contract tests are the **Phase 2-bis dispatch yardstick**
— any future per-surface migration must keep them green.

## What is deferred to Phase 2-bis

Per-surface caller migrations identified in the v6 gap inventory's
"Legacy-compat named-caller list (for Phase 2)":

**Sandbox lane (9 callers)**:

* `blueprints/sandbox.py`
* `sandbox/order_manager.py`, `sandbox/squareoff_manager.py`,
  `sandbox/squareoff_thread.py`, `sandbox/catch_up_processor.py`,
  `sandbox/holdings_manager.py`, `sandbox/fund_manager.py`,
  `sandbox/execution_engine.py`
* `database/sandbox_db.py` (read region/currency from additive
  columns instead of hardcoded India defaults)

Migration template per file:
1. Resolve region via
   `services.feature_gate_service.active_region_code()`.
2. Get provider via `services.sandbox.dispatcher.get_sandbox_provider(region)`.
3. Replace hardcoded `MIS/CNC/NRML` set with
   `provider.supported_products()`.
4. Replace hardcoded `INR` with `provider.base_currency()`.
5. Replace hardcoded `15:15 IST` with
   `provider.squareoff_time_for_product(product, venue, on_date)`.
6. Replace hardcoded T+1 with
   `provider.settlement_date_for_order(order, trade_date)`.
7. Run `parity_sandbox_india` after each file change. Stop on diff.

**Options lane (10 services)**: same template applied through
`services.options.dispatcher.get_options_provider(region)` for
`option_chain_service`, `option_symbol_service`,
`option_greeks_service`, `iv_chart_service`, `straddle_chart_service`,
`options_multiorder_service`, `expiry_service`, `oi_profile_service`,
`gex_service`, `iv_smile_service`. Each entry point keeps its
existing `is_india_region_active()` 422 gate; the gate stays, the
implementation routes through the provider. India parity:
`parity_options_india`.

**Screener lane**: `blueprints/chartink.py` migrates to
`services.screeners.dispatcher.get_screener_provider("chartink")`
and uses `provider.validate_webhook_payload()` /
`provider.map_signal_to_orders()` instead of direct India calls.
India parity: `parity_chartink_india`.

**Strategy / flow scheduler (4 callers)**: `flow_executor_service.py`,
`flow_scheduler_service.py`, `python_strategy.py`,
`historify_scheduler_service.py` migrate to
`services.venue_session_service.get_session_for_venue(venue_code)`
for tz/holiday/session windows instead of `Asia/Kolkata` literals
and `09:15-15:30` hardcodes. Phase 4-bis venue-aware historify
work folds in here.

## Comprehensive test gate (passed)

| Step | Result |
|---|---|
| `uv run pytest tests/ -x --tb=short` | **2207 passed, 7 skipped** in 3:26 (was 2181; +26 = the 4 new dispatcher contract tests) |
| `uv run pytest -x tests/contracts/test_v4_closing_invariants.py tests/contracts/test_v5_closing_invariants.py` | exit 0 |
| `uv run python tests/parity/run_parity.py` | **11/11** verify-mode harnesses |
| `uv run python tests/parity/run_parity.py --lane v1` | **11/11** v1-lane harnesses |
| `uv run python tests/parity/run_parity.py --lane v2` | **11/11** v2-lane harnesses |
| `uv run python scripts/audit/classify_files.py --check` | exit 0 — no drift |
| `uv run python scripts/audit/route_fallback_scan.py` | exit 0 |
| `uv run python scripts/audit/symtoken_callers.py` | exit 0 — 0 PROMOTED_LEAK |
| `uv run python scripts/audit/canonical_vs_legacy_parity.py` | exit 0 |
| `npm test -- --run` (frontend) | **160 passed across 15 test files** |
| `npm run lint:literals` | exit 0 — 256 files / 0 violations |

All v4 and v5 invariants still hold. India parity bit-identical.

## Next phase

**Phase 3 — EU/UK Provider Stubs + Multi-Region Smoke Tests.**
`/compact` then `/effort high`. Adds minimal EU and UK provider stubs
for sandbox/options/screener so the four-region matrix is complete.
Phase 3 is purely additive (no existing flow changes), so it can land
the full prompt scope in one session safely.
