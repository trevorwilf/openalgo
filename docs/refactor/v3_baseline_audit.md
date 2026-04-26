# v3 baseline audit

The market-agnostic refactor has had two prior passes:

* **Prompt v1** — `market-agnostic-phases_Claude_code.md` — landed
  v2-lane scaffolding (BrokerOrderTranslator, instrument resolver,
  broker rules, observability, Alpaca MVP, ADRs 0001–0005,
  lane-isolation contract tests).
* **Prompt v2** — `openalgo_market_agnostic_v2_claude_code_prompt.md`
  — landed boundary lock (literal scanner), region plugin schema v2,
  promoted dispatch fail-closed for **orders**, TZ decoupling,
  capability-driven frontend, region gating for option/sandbox/
  analyzer, broker compliance harness, Schwab/Webull readiness docs
  and framework extensions (combo orders, streaming protocols,
  product capabilities). ADRs 0006–0015.

This document is the v3 starting point. It cross-checks the v2
deliverables against the current repo and lists every gap that v3
phases must close.

## A. Prior-prompt-claimed deliverables — current state

### ADRs 0006–0015

| ADR | File | Purpose |
|---|---|---|
| 0006 | `docs/adr/0006-literal-scanner-and-failclosed-capabilities.md` | India literal scanner + fail-closed capability inference |
| 0007 | `docs/adr/0007-region-plugin-schema-v2.md` | Region plugin schema v2 (venues, sessions, calendar, symbol_display, feature_flags) |
| 0008 | `docs/adr/0008-promoted-failclosed-and-account-context.md` | v2 orders fail-closed dispatch + AccountContext model |
| 0009 | `docs/adr/0009-tz-decoupling-and-holiday-migration.md` | TZ decoupling + holiday data migration |
| 0010 | `docs/adr/0010-capability-driven-frontend.md` | Capability-driven frontend |
| 0011 | `docs/adr/0011-region-gating-india-features.md` | Region gating for option/sandbox/analyzer |
| 0012 | `docs/adr/0012-broker-plugin-compliance-harness.md` | Broker compliance harness |
| 0013 | `docs/adr/0013-combo-order-model.md` | Normalized combo order model |
| 0014 | `docs/adr/0014-broker-streaming-contracts.md` | Broker streaming protocols |
| 0015 | `docs/adr/0015-product-specific-capability-matrix.md` | Per-product capability matrix |

All 10 ADRs are present on disk.

### Test files added by prior prompts

| File | Status | Notes |
|---|---|---|
| `tests/contracts/test_lane_isolation.py` | present | extended in v3 Phase 0 |
| `tests/contracts/test_literal_scanner.py` | present | covers ADR 0006 |
| `tests/compliance/broker_plugin_compliance.py` | present | shared mixin |
| `tests/compliance/test_alpaca_compliance.py` | present | strict |
| `tests/compliance/test_indian_brokers_baseline.py` | present | non-strict |
| `tests/compliance/test_architecture_readiness.py` | present | architecture gate |
| `tests/fakes/fake_us_translator.py` | present | mock |
| `tests/fakes/fake_us_market_data.py` | present | mock |

### Modules added by prior prompts

All present on disk:

* `domain/account_context.py`, `domain/broker_streaming.py`,
  `domain/broker_market_data.py`, `domain/broker_translator.py`,
  `domain/broker_rules.py`, `domain/capabilities.py`,
  `domain/currency.py`, `domain/instrument_ref.py`,
  `domain/market_data.py`, `domain/orders.py`, `domain/regions.py`
* `services/feature_gate_service.py`,
  `services/account_context_service.py`,
  `services/broker_market_data_registry.py`,
  `services/broker_streaming_registry.py`,
  `services/broker_translator_registry.py`,
  `services/instrument_resolution.py`,
  `services/instrument_sync_service.py`,
  `services/market_region_service.py`,
  `services/rule_enforcement.py`,
  `services/venue_session_service.py`
* `restx_api/v2/{accounts,bars,broker_compliance,capabilities,instruments,orders,quotes,regions,venues}.py`
* `market_regions/{india,us,eu,uk}/plugin.json`
* `upgrade/migrate_holidays_to_venue_calendar.py`
* `docs/refactor/{schwab_readiness,webull_readiness,broker_compliance_matrix}.md`
* `broker/alpaca/` plugin with `PROMOTED` sentinel

## B. Verified gaps still present

Each row was cross-checked against the current code on `dev` (Phase 0
of v3, before any v3 changes). Gap status legend:

* **CONFIRMED** — gap still present, fix scope is open.
* **PARTIAL** — gap partially closed but residual leak remains.
* **FIXED-SINCE** — gap was closed by a follow-up not on the v2
  prompt's roadmap.

| # | Gap | Code reference | Status | v3 phase |
|---|---|---|---|---|
| 1 | v2 quotes legacy-fallback to `services.quotes_service.get_quotes_with_auth` | `restx_api/v2/quotes.py:166,181` | CONFIRMED | Phase 2 |
| 2 | v2 bars legacy-fallback to `services.history_service.get_history_with_auth` | `restx_api/v2/bars.py:147,156` | CONFIRMED | Phase 2 |
| 3 | `flow_executor_service` defaults `exchange="NSE"`, `product="MIS"` with no region gate | `services/flow_executor_service.py` (multiple sites) | CONFIRMED | Phase 4 |
| 4 | `expiry_service` not region-gated | `services/expiry_service.py` | CONFIRMED | Phase 4 |
| 5 | `iv_chart_service`, `gex_service`, `option_greeks_service`, `options_multiorder_service`, `synthetic_future_service`, `straddle_chart_service`, `vol_surface_service` not region-gated | `services/*_service.py` | CONFIRMED | Phase 4 |
| 6 | `historify_db` hardcoded `ist_offset = 19800` for non-India aggregation | `database/historify_db.py:1001-1014, 1098-1107, 2584-2585` | CONFIRMED | Phase 4 |
| 7 | `telegram_db` defaults user `timezone="Asia/Kolkata"` for all users | `database/telegram_db.py:171-183, 629-637` | CONFIRMED | Phase 4 |
| 8 | `utils/number_formatter.format_indian_number` / `format_inr_currency` used outside India context | `utils/number_formatter.py:8, 54-68` | CONFIRMED | Phase 4 |
| 9 | Frontend `lib/utils.ts` currency formatting may infer INR from broker name | `frontend/src/lib/utils.ts` | CONFIRMED | Phase 4 |
| 10 | Promoted v2 quote/bar paths do NOT route through canonical resolver for non-India | by inspection | CONFIRMED | Phase 2 |
| 11 | `database.symbol` and `database.token_db_enhanced` reads not classified across all callers | by inspection | CONFIRMED | Phase 3 |
| 12 | Mock Schwab-like / Webull-like end-to-end framework readiness fixtures absent | absent | CONFIRMED | Phase 6 |
| 13 | `python_strategy`, `strategy`, `chartink` blueprints schedulers IST-bound, not region-gated | by inspection | CONFIRMED | Phase 5 |
| 14 | `restx_api/schemas.py` (V1) India-specific options grammar not classified as legacy compatibility | `restx_api/schemas.py` | CONFIRMED | Phase 1 (classification only) |
| 15 | Frontend `LEGACY_FALLBACK_EXCHANGES = ['NSE','BSE','NFO','BFO','CDS','MCX','CRYPTO']` literal in promoted code | `frontend/src/hooks/useSupportedExchanges.ts:33` | CONFIRMED | Phase 1 |
| 16 | Broker compliance harness has no equivalent for region-plugin compliance | absent | CONFIRMED | Phase 6 |
| 17 | No structured route fallback inventory document | absent | CONFIRMED | Phase 0 (this phase) |

## C. Recommendations per gap

The phase column in the table above is the recommendation. The v3
prompt closes them in this order:

* **Phase 0 (this phase)** — gap 17 (route inventory), file
  classification, literal scanner hardening.
* **Phase 1** — gaps 14, 15: import lock, v1 schema legacy stamp,
  frontend literal containment.
* **Phase 2** — gaps 1, 2, 10: v2 quotes/bars fail-closed + canonical
  resolver adoption.
* **Phase 3** — gap 11: SymToken caller audit + resolver hardening.
* **Phase 4** — gaps 3–9: service region gating + historify venue tz +
  currency propagation + telegram defaults.
* **Phase 5** — gap 13: strategy/scheduler region gating + frontend
  locale + region API completeness.
* **Phase 6** — gaps 12, 16: Schwab/Webull mock plugins for end-to-end
  framework readiness + region-plugin compliance.

After Phase 6 every gap above is closed and the framework is provably
ready for real Schwab/Webull plugin implementation (without writing
any real Schwab/Webull API code).

## Cross-references

* `docs/refactor/route_fallback_inventory.md` — generated by
  `scripts/audit/route_fallback_scan.py`. Source of truth for the
  v1/v2 lane disposition.
* `docs/refactor/file_classification.md` — generated by
  `scripts/audit/classify_files.py`. Source of truth for the
  PROMOTED_CORE / LEGACY_INDIA / REGION_PLUGIN / BROKER_PLUGIN /
  COMPATIBILITY_SHIM bucket of every Python source file.
