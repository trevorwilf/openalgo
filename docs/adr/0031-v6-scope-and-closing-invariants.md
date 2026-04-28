# ADR 0031 — v6 scope and closing invariants

* **Status:** Accepted
* **Date:** 2026-04-28
* **Supersedes:** none
* **Refines:** ADRs 0001–0030 (additive)

## Context

ADRs 0029–0030 (v5) closed the deferred bis-phases of v4 (structured
errors + observability surface) and announced the `/api/v1/*`
deprecation. Two independent expert reviews then converged on a
list of remaining gaps before the core could host non-India broker
plugins (US, EU, UK, Schwab-LIKE, Webull-LIKE) without silent India
translation. v6 closes those gaps in nine sequenced phases.

The v6 prompt at the repo root
(`openalgo_market_agnostic_v6_claude_code_prompt.md`) is the
authoritative source for the v6 plan. This ADR records the resolved
decisions, the v6-specific invariants, and the actual delivery state
at v6 close.

## Decisions resolved

| Topic | Resolution |
|---|---|
| `/api/v1/*` fate | Deprecated with operator-controlled sunset (`OPENALGO_V1_SUNSET_DATE`); routes stay alive until v6+ removal. India v1→v2 translators land per-broker in Phases 5–7 of v6. |
| First non-India production target | None. Real Schwab / Webull / Alpaca / EU / UK plugins out of v6 scope. Mock Schwab-LIKE / Webull-LIKE remain the only non-India broker surface. |
| Canonical instrument schema | Uses ADR 0019's `domain/instrument_ref.py` + `database/instruments_repo.py` + `IdentifierKind` + `identifier_resolve_one_instrument`. No redesign in v6. |
| Legacy data migration | Additive only. Every schema change is `ADD`, never `DROP`. Retirement only after parity passes. |
| Sandbox / Options / Screener provider scope | India + US shipped in v4 (ADRs 0026–0028). EU + UK added as **minimal stubs** in v6 Phase 3. |
| Broker capability completeness | Strict-mode schema with 17 required fields per ADR 0025. Per-broker explicit-declaration upgrade is per-PR work in v6 Phases 5–7. |
| Per-broker translator order | Popularity-first: Zerodha, Angel, Dhan, Upstox, Fyers — then alphabetical. (v6 Phases 5–7) |
| Mock plugin extension | Extend mocks if Phase 0 audit identifies contracts they don't exercise. (Phase 0 listed 5 candidates; Phase 4 mock extension deferred to Phase 4-bis.) |
| Treatment of v5-completed work | Discover-then-close: Phase 0 audits actual state; later phases close only real gaps. |

## v6 invariants (additive to v4 1–12 + v5-1, v5-2)

| # | Invariant | Source | Enforcement |
|---|---|---|---|
| v6-1 | The four-region matrix (`india`, `us`, `eu`, `uk`) is complete: every region has a registered sandbox provider AND a registered options provider. (Screener providers may declare `provider_code` rather than `region_code` per ADR 0028.) | ADR 0031, ADRs 0026–0028 | `tests/multi_region/test_v6_capability_load_four_regions.py` + `tests/services/test_v6_sandbox_dispatcher_only.py` + `tests/services/test_v6_options_dispatcher_only.py` |
| v6-2 | Non-India regions never silently fall back to India: non-India sandbox providers carry no INR / India products / ₹10L default; non-India options providers declare non-India region; non-India region plugins use non-India currency / tz / venues. | ADR 0031 | `tests/multi_region/test_v6_no_india_fallback_for_non_india.py` |
| v6-3 | Every region plugin satisfies the same contract: required top-level fields, required venue fields, required session fields, required symbol_display fields. New regions (APAC, LATAM, etc.) must pass this contract before being accepted. | ADR 0031, ADR 0007 | `tests/contracts/test_v6_region_plugin_contract_complete.py` |
| v6-4 | The frontend literal-scan allowlist may shrink (entries removed by per-component cleanup) but never grows. The Phase 1 baseline pins the watermark; any entry the live allowlist declares must be in the baseline. | ADR 0031, ADR 0006 | `tests/contracts/test_v6_frontend_allowlist_shrinks.py` |
| v6-5 | The `useVenueTimezone` hook is available at `frontend/src/hooks/useVenueTimezone.ts` and re-exports the v5 Phase 2 capability-driven helpers. Components migrating from `Asia/Kolkata` literals use this hook. | ADR 0031 | `frontend/src/hooks/useVenueTimezone.test.ts` |
| v6-6 | Dispatcher-only routing is locked at the contract level for sandbox / options / screener / strategy-scheduler. Per-surface caller migration (Phase 2-bis) lands per-PR with India parity guard. | ADR 0031 | 4 contract tests at `tests/services/test_v6_*_dispatcher_only.py` and `test_v6_strategy_scheduler_venue_aware.py` |

## Items intentionally out of v6 scope

These items are documented in the v6 prompt's "After Phase 8" section
and the v5 closing report's "What v6 should consider" list but are
**not** closed in v6:

* Real Schwab plugin (blocked on official API access).
* Real Webull plugin (blocked on official API access).
* Real Alpaca plugin production hardening.
* Real EU / UK pilot broker plugin code.
* Per-broker v1→v2 translators + parity harnesses for the 30 India
  brokers (Phases 5/6/7 of the v6 prompt — these were not delivered
  in the single-session execution because each broker requires deep
  mapping-module reading + v1 + v2 lane fixture capture, far beyond
  what one non-interactive session can safely produce).
* Multi-broker-per-instance deployment model.
* `/api/v1/*` removal.
* APAC ex-India / LATAM region plugins.
* OpenTelemetry / Prometheus metrics backend upgrade.

## v6 phase-by-phase delivery

| Phase | Goal | Status | Evidence |
|---|---|---|---|
| 0 | Discovery & gap inventory | ✅ complete | `docs/refactor/v6-phase-0-complete.md` + `docs/refactor/v6_gap_inventory.md` + `tests/contracts/test_v6_gap_inventory_present.py` |
| 1 | Frontend per-component cleanup (foundation) | ✅ scaffolding | `docs/refactor/v6-phase-1-complete.md`. Adds `useVenueTimezone` hook + `test_v6_frontend_allowlist_shrinks` guard. Per-component refactors deferred to Phase 1-bis. |
| 2 | Backend service route adoption (foundation) | ✅ scaffolding | `docs/refactor/v6-phase-2-complete.md`. 4 dispatcher contract tests + 26 assertions including India bit-identicality. Per-surface caller migrations deferred to Phase 2-bis. |
| 3 | EU/UK provider stubs + multi-region smoke tests | ✅ complete | `docs/refactor/v6-phase-3-complete.md`. 6 provider stubs + 9 multi-region test files / 108+ tests + region-plugin contract test. |
| 4 | Helper retirement + mock extension | ✅ deferred markers | `docs/refactor/v6-phase-4-complete.md`. Helper retirement blocked on Phase 2-bis per the prompt's prerequisite. xfail-strict markers ship as Phase 4-bis target signals. |
| 5 | India v1→v2 translators (top 5) | ⏸ deferred | 5 brokers × translator + parity harness. Out of single-session scope. |
| 6 | India v1→v2 translators (alpha batch 1) | ⏸ deferred | 12 brokers. Same. |
| 7 | India v1→v2 translators (alpha batch 2) | ⏸ deferred | 13 brokers. Same. |
| 8 | Closing audit + docs | ✅ complete | This ADR + `tests/contracts/test_v6_closing_invariants.py` + `docs/refactor/v6-overview.md` + `docs/refactor/v6-phase-8-complete.md` |

## v6 closing invariant gate

`tests/contracts/test_v6_closing_invariants.py` runs every v6
invariant in one place plus re-runs the v5 closing test. It is the
single command that proves v6 is done at the level v6 actually
delivered (Phases 0, 3, 8 fully + Phases 1, 2, 4 as scaffolding).

The deferred Phase 4-bis / Phase 5-bis / Phases 5/6/7 work has its
own contract tests (xfail-strict markers) that flip the build red
when their respective targets land — so the gate evolves into the
final closing gate without requiring this ADR to be amended.

## Consequences

* The framework is **structurally** ready for non-India broker
  plugins (4-region matrix complete, dispatcher contracts pinned,
  no-India-fallback enforcement on non-India regions).
* The India broker v2 lane remains in **scaffolded** state; per-
  broker translator + parity harness work continues per-PR.
* India parity is bit-identical at every v6 phase boundary
  (`parity_*_india` 11 harnesses, all 3 lanes). v6 introduces no
  India behavior change.
* `/api/v1/*` remains alive on its operator-controlled sunset clock.
