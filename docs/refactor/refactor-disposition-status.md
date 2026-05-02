# Refactor disposition status (C-P2-028)

This file dispositions every "deferred" item across the v3 → v6
phase docs and the market-agnostic refactor's bis-phases. Each
entry is bucketed as one of:

* **Implemented** — work landed under a different phase / commit
  (with link).
* **Still deferred with owner** — explicitly named v9-bis or future
  engagement.
* **Intentionally India-only** — per ADR 0004 / ADR 0005, the v1
  lane is India-only by design; the deferred item never closes
  because the bucket itself stays.

Generated at the end of the market-agnostic refactor's main phases
(2026-05-02). Future bis-phases append rows; do not retroactively
mutate.

## Bucket: Implemented

| Deferred item | Closed by | Notes |
|---|---|---|
| v6 Phase 4-bis-1 — `_legacy_india_region_for_compat` retired | v6 Phase 4-bis-helper-retirement | Pinned by `tests/contracts/test_v6_helper_retired.py` |
| v6 Phase 4-bis mocks (Schwab/Webull combo, position currency, account context) | v6 Phase 4-bis-mocks | ADR 0031 invariants v6-11 |
| v6 Phase 5-bis runtime activation + dispatcher MPP | v6 Phase 5-bis | `services/india_translator_bootstrap.py` + `services/promoted_mpp_service.py` |
| v6 Phase 5-bis-2 — 30 India broker translators ALL_GREEN | Market-agnostic Phase 6 | `docs/refactor/v6-translator-parity-status.md` STATUS: ALL_GREEN |
| v3 Phase 1 v6 — `useVenueTimezone` hook | v6 Phase 1 (already shipped) | Market-agnostic Phase 4 added `useRegionCapabilities` on top |
| v6 Phase 2-bis-sandbox — `order_manager` validates via dispatcher | v6 Phase 2-bis-sandbox | Pinned by `test_v6_sandbox_dispatcher_caller_migration.py` |
| v6 Phase 2-bis-options — 4 services dispatcher integration | v6 Phase 2-bis-options | partial; rest covered by Phase 2-bis-3 follow-up |
| v6 Phase 2-bis-screener — Chartink dispatcher | v6 Phase 2-bis-screener | Pinned |
| v6 Phase 2-bis-strategy — flow_executor venue session | v6 Phase 2-bis-strategy | Pinned |
| Market-agnostic T-09 (HOLIDAYS_2026) | Phase 2 | `market_regions/india/holidays.py` |
| Market-agnostic T-10 (5 IST module-level constants) | Phase 2 | re-exports |
| Market-agnostic T-11 (squareoff data) | Phase 2 | `market_regions/india/squareoff.py` |
| Market-agnostic T-12 (qty-freeze data) | Phase 2 | `market_regions/india/qty_freeze.py` |
| Market-agnostic T-14 (options grammar data) | Phase 2 | `market_regions/india/options_grammar.py` |
| Market-agnostic T-15 (locale data) | Phase 2 | `market_regions/india/locale.py` |
| Market-agnostic T-20 (8 critical service migration) | Phase 3 | All 8 services PROMOTED_CORE |
| Market-agnostic T-21 (WS topic_format) | Phase 5 | `_split_topic_venue_and_symbol` capability-driven |
| Market-agnostic T-22 (MPP capability flags) | Phase 5 | 9 + 2 broker plugin.json updates |
| Market-agnostic T-25 (ALL_GREEN parity) | Phase 6 | All 30 brokers verified |
| Market-agnostic Phase 7a — RegionPlugin Protocol | Phase 7 | `domain/region_plugin.py` |
| Market-agnostic Phase 7a — IndiaRegionPlugin | Phase 7 | `market_regions/india/plugin.py` |
| Market-agnostic Phase 7b — USRegionPlugin | Phase 7 | NYSE/NASDAQ holidays + OCC-21 + USD locale + T+1 |
| Market-agnostic T-23 logical | Phase 9 | India-gated v1 mount |
| Market-agnostic T-33 (sunset machinery) | Phase 9 | `OPENALGO_V1_SUNSET_DATE` enforcement |
| Market-agnostic T-26 (install scripts $OPENALGO_DEPLOY_TZ) | Phase 8 | 5 install scripts |
| Market-agnostic T-29 (multi-region matrix) | Phase 8 | `multi_region_broker_compatibility_matrix.md` |
| Market-agnostic C-P2-029 (future-broker checklist) | Phase 8 | `future-broker-onboarding-checklist.md` |
| Market-agnostic C-P2-030 (release-gate dashboard) | Phase 8 | `release-gate-dashboard.md` |
| Market-agnostic T-16 partial (useRegionCapabilities hook) | Phase 4 | foundation; per-component drain in Phase 4-bis-2 |
| Market-agnostic T-19 partial (MasterContract + HealthMonitor) | Phase 4 | 2 of 4 pages migrated |
| Market-agnostic T-27 (sqlite_downloader venue tz) | Phase 8-bis | `DOWNLOAD_VENUE_TZ` env var |
| Market-agnostic T-28 (region-aware examples) | Phase 8-bis | `--region` arg added |
| Market-agnostic C-P2-027 (label India examples) | Phase 8-bis | docs/api/README.md region note |

## Bucket: Still deferred with owner (v9-bis future engagement)

| Deferred item | Owner / future engagement | Notes |
|---|---|---|
| Market-agnostic T-13 (sandbox dispatcher consumer wiring) | v9-bis Phase 2-bis-3 | `blueprints/sandbox.py` still bypasses `services.sandbox.dispatcher`; data layer fully relocated |
| Market-agnostic T-14 (options dispatcher consumer wiring) | v9-bis Phase 2-bis-3 | `services/option_*_service.py` still inline |
| Market-agnostic T-15 partial (per-caller switch to format_currency_amount) | v9-bis Phase 2-bis-2 | re-export bridge keeps callers working today |
| `database/sandbox_db.py:299` schema change to `DEFAULT NULL` | v9-bis Phase 2-bis-2 | `Decimal("1000000.00")` provider seed exists in IndiaSandboxProvider |
| Market-agnostic T-16 partial (lib/utils.ts + lib/format/currency.ts inline INR/JPY chain) | v9-bis Phase 4-bis-1 | `useRegionCapabilities` hook is the foundation |
| Market-agnostic T-17 (Flow constants + 14 flow nodes) | v9-bis Phase 4-bis-2 | per-component UX work |
| Market-agnostic T-18 (strategyMath.ts type-system migration) | v9-bis Phase 4-bis-2 | OptionType union → OptionRight enum |
| Market-agnostic T-19 partial (Historify + SandboxPnL IST schedule labels) | v9-bis Phase 4-bis-1 | UX redesign |
| Market-agnostic T-23 physical relocation (37 files into market_regions/india/legacy_v1/) | v9-bis Phase 9 | Logical conditional mount in Phase 9 delivers same operator semantic |
| Market-agnostic T-24 (docs/api split into v1/v2) | v9-bis Phase 8-bis-2 | mechanical doc reorg |
| Market-agnostic T-34 (drain frontend allowlist 78 → ≤ 2) | v9-bis Phase 4-bis-2 | helper script `find_stale_allowlist.mjs` ships in Phase 4 |
| Market-agnostic T-35 partial (LEGACY_INDIA bucket < 50) | v9-bis Phase 9 | depends on T-23 physical relocation |
| Phase 4-bis-2 — capability hook, flow constants, ConfigPanel, PlaceOrderDialog, MarketTimings, CustomStraddle, scheduler-tied pages | v9-bis Phase 4-bis-2 | Browser-verified per-component migration |
| Phase 2-bis-2 — sandbox squareoff/catch_up/holdings/execution_engine; 6 remaining options services; chartink legacy parser; flow_scheduler/python_strategy/historify_scheduler venue-aware | v9-bis Phase 2-bis-2 | deeper dispatcher migrations beyond the 4 covered in v6 Phase 2-bis-options |
| Phase 4-bis-2 — master-contract refresh-policy execution + rule_enforcement.check_order entitlement integration | v9-bis Phase 4-bis-2 | broker-side runtime work |
| `IndiaSandboxProvider._INITIAL_FUNDS` (₹10L) vs `sandbox/fund_manager.py` (₹1Cr) reconciliation | v9-bis Phase 2-bis-2 | known discrepancy |
| EU + UK Python `RegionPlugin` implementations | v9-bis Phase 7-bis | Manifests + stub providers ship; Python plugin classes are future work |
| Real Schwab plugin | v9-bis (blocked on official API access) | Out of every market-agnostic phase |
| Real Webull plugin | v9-bis (blocked on official API access) | Out of every market-agnostic phase |
| Real Alpaca production hardening | v9-bis | Out of every market-agnostic phase |
| Real EU / UK pilot broker plugins | v9-bis | Out of every market-agnostic phase |
| `/api/v1/*` removal after operator-controlled sunset | v9-bis | Phase 9 ships the machinery; the actual cutover is a deployment decision |
| Multi-broker-per-instance deployment | v9-bis (out of v6 scope) | ADR 0001 invariant |
| APAC ex-India / LATAM region plugins | v9-bis (future engagement) | not in any phase's scope |
| OpenTelemetry / Prometheus metrics backend upgrade | v9-bis (out of v6 scope) | telemetry follow-up |

## Bucket: Intentionally India-only (no closing date)

| Item | Why |
|---|---|
| `analyzer` blueprint stays India-limited | ADR 0004 — sandbox simulator is India-tuned; non-India brokers lack the regulatory rails (SEBI margin, MIS auto-square-off) |
| `/api/v1/*` lane stays India-only forever | ADR 0005 — the legacy lane is the India compat surface; non-India brokers route through `/api/v2` |
| `services.options.providers.india` lot-size table duplicates `market_regions/india/options_grammar.py` | Phase 2 ships data only; provider keeps its own copy until Phase 7 wires it as a single import — Phase 7 IndiaRegionPlugin pins both copies in sync via `tests/region_loader/test_india_options_grammar_byte_identical.py` |
| `LEGACY_INDIA_MPP_*_BROKERS` frozensets in `services.promoted_mpp_service` | Inventory-only after Phase 5 T-22; runtime is capability-driven |
| `legacy_compat_shim.valid_exchanges` carries `CRYPTO` | CRYPTO is a meta-classifier in `VALID_EXCHANGES`, not a real venue. Stays in the compat shim because real venues are in `manifest.venues[]` |

## How to update this doc

1. When a deferred item closes, move its row from "Still deferred" to
   "Implemented" with a link to the closing commit / PR.
2. When a new bis-phase ships, append rows for any newly-acknowledged
   deferrals.
3. Do NOT retroactively mutate "Implemented" rows; the doc is a
   chronological audit trail.
