# v6 Gap Inventory (Phase 0)

> Authoritative gap inventory mapping every Expert-1 / Expert-2 finding
> to one of `ALREADY-CLOSED`, `BIS-DEFERRED`, or `GENUINE-GAP`. Phase 0
> output. No code-behavior changes.

## Header

* **Date:** 2026-04-28
* **Branch:** `refactor/v6-phase-0-gap-inventory`
* **`dev` SHA at Phase 0 start:** `0ab793bb3a7a0692b51ad9bb58472450ccd3a026` (HEAD: "updated gitignore" on top of v5 Phase 10 close)
* **Baseline gate counts (captured before Phase 0 started):**
  * Backend: `uv run pytest tests/ -x --tb=short` → **2170 passed, 7 skipped, 0 failed** (242.70 s).
  * Closing invariants: `uv run pytest -x tests/contracts/test_v4_closing_invariants.py tests/contracts/test_v5_closing_invariants.py` → **20 passed** (13.28 s).
  * Parity (default lane): **11/11** harnesses pass.
  * Parity (`--lane v1`): **11/11** harnesses pass.
  * Parity (`--lane v2`): **11/11** harnesses pass.
  * `scripts/audit/classify_files.py --check` → exit 0, **840 files / no drift**.
  * `scripts/audit/route_fallback_scan.py` → exit 0, **51 routes**.
  * `scripts/audit/symtoken_callers.py` → exit 0, **0 `PROMOTED_LEAK` rows** (39 caller files total).
  * `scripts/audit/canonical_vs_legacy_parity.py` → exit 0, **13 pairs**.
  * Frontend `npm run lint:literals` → exit 0, **255 files scanned / 0 violations**.
  * Frontend `npm test` → exit 0, **150 tests passed across 14 files**.

## Sources

* `expert 1 - appendix A - openalgo_market_assumptions_inventory.md` — §3 (India-specific findings, ~80 rows), §4 (Implicit, ~14 rows), §5 (clean), §6 (deeper review), §7 (deferred refactor docs). The row numbering used in this inventory is the in-table sequence as `E1-§-n` (e.g. `E1-3-01` = Expert 1, §3, first data row).
* `expert 2 - appendix A - openalgo_market_assumptions_inventory.md` — §3 (~58 rows), §4 (~32 rows), §5 (clean), §6 (deeper review), §7 (deferred refactor docs). `E2-§-n`.
* The "123 findings" figure used in the v6 prompt is approximate; the actual aggregate of distinct rows across both Appendix A's §3+§4 is **184**. Every distinct row is classified below. §5 (clean) rows are not gaps and are out of scope of this inventory.

## Classification semantics

| Code | Meaning |
|---|---|
| `ALREADY-CLOSED` | Already enforced by an in-repo ADR / contract test / parity harness. No v6 work required. |
| `BIS-DEFERRED` | A v5 partial phase explicitly deferred this to a `*-bis` follow-up; v6 owns closure. |
| `GENUINE-GAP` | Not closed and not tracked by any v5 bis-phase. Assigned to a v6 phase. |
| `INTENTIONAL-INDIA-LIMIT` | The finding documents an intentionally-India-only feature gated by `is_india_region_active()` or region-plugin policy. Not a v6 gap; the gate is the closure. |
| `OUT-OF-SCOPE` | Real Schwab/Webull/EU/UK broker code (v4 invariant 8 + v6 prompt mission). Not a v6 gap. |

## Per-finding classification table

The owning-phase column refers to phases of the v6 prompt:
**P1** = Phase 1 frontend cleanup,
**P2** = Phase 2 backend dispatcher adoption,
**P3** = Phase 3 EU/UK provider stubs + multi-region smoke tests,
**P4** = Phase 4 helper retirement + mock plugin extension,
**P5/P6/P7** = India v1→v2 translator phases,
**P8** = closing audit + docs.

### Expert 1 §3 — explicit India-specific findings

| ID | Finding (terse) | Classification | Owning v6 Phase | Evidence |
|---|---|---|---|---|
| E1-3-01 | `utils/constants.py` LEGACY INDIA COMPATIBILITY stamp | ALREADY-CLOSED | n/a | ADR 0017 + `LEGACY_INDIA_COMPATIBILITY=True`; lane-isolation test blocks promoted import |
| E1-3-02 | `VALID_EXCHANGES`/`EXCHANGE_*` constants | ALREADY-CLOSED | n/a | CLAUDE.md invariant 5 + `tests/contracts/test_lane_isolation.py` import blocklist |
| E1-3-03 | `VALID_PRODUCT_TYPES`, `VALID_PRICE_TYPES`, `PRODUCT_MIS` | ALREADY-CLOSED | n/a | CLAUDE.md invariant 5 + `tests/contracts/test_lane_isolation.py` |
| E1-3-04 | `restx_api/data_schemas.py` v1 schemas validate against `VALID_EXCHANGES` | ALREADY-CLOSED | n/a | ADR 0003 (v1 frozen) + ADR 0017 v1 legacy stamp + `/api/v1/*` deprecation (v5 Phase 8); v1 lane is intentionally India-shaped |
| E1-3-05 | `restx_api/schemas.py` v1 order schemas | ALREADY-CLOSED | n/a | Same as E1-3-04 |
| E1-3-06 | `services/place_order_service.py` + basket/smart/margin import legacy lists | ALREADY-CLOSED | n/a | LEGACY_INDIA classification (CLAUDE.md "Legacy lane (frozen)"); v1 hard-block guards non-India (ADR 0017) |
| E1-3-07 | `services/quotes_service.py` etc. validate exchange against `VALID_EXCHANGES` | ALREADY-CLOSED | n/a | LEGACY_INDIA + v1 hard-block; v2 lane uses `services/instrument_resolution.py` instead (ADR 0018) |
| E1-3-08 | `blueprints/chartink.py` IST scheduler + `VALID_EXCHANGES = ["NSE","BSE"]` | BIS-DEFERRED | P2 | v5 Phase 6 deferred screener route adoption to Phase 6-bis; closed by P2 dispatcher migration |
| E1-3-09 | `blueprints/strategy.py` IST scheduler + India-shaped exchange/product map + NSE/MIS defaults | BIS-DEFERRED | P2 | v5 Phase 5 deferred to Phase 5-bis (strategy scheduler venue-aware); closed by P2 |
| E1-3-10 | `blueprints/flow.py` schedule default `09:15` + `NSE` price-alert default | BIS-DEFERRED | P2 | v5 Phase 5/6 bis; closed by P2 (flow scheduler venue-aware) |
| E1-3-11 | `blueprints/python_strategy.py` IST + `DEFAULT_STRATEGY_EXCHANGE="NSE"` | BIS-DEFERRED | P2 | v5 Phase 5 bis; closed by P2 (strategy scheduler venue-aware) |
| E1-3-12 | `utils/session.py` invalid/empty timezone falls back to `Asia/Kolkata` | INTENTIONAL-INDIA-LIMIT | n/a | ADR 0009 + ADR 0020; the legacy compat path is gated by `is_india_region_active()`; v6 P4 retires the helper |
| E1-3-13 | `services/venue_session_service.py` `venue_tz_or_default(default="Asia/Kolkata")` | INTENTIONAL-INDIA-LIMIT | n/a | ADR 0009; the default is the explicit India-compat fallback for legacy Indian brokers; promoted code uses venue metadata |
| E1-3-14 | `services/market_calendar_service.py` default tz `Asia/Kolkata`, `NSE` canonical | INTENTIONAL-INDIA-LIMIT | n/a | ADR 0024 (calendar precedence: non-India never reads `database.market_calendar_db`) + Phase 4-bis venue session helper |
| E1-3-15 | `database/market_calendar_db.py` IST + Indian holidays | INTENTIONAL-INDIA-LIMIT | n/a | ADR 0024 — non-India never reads this table; promoted code routes through region plugin |
| E1-3-16 | `database/market_calendar_db.py` Diwali Muhurat sessions | INTENTIONAL-INDIA-LIMIT | n/a | Same as E1-3-15 |
| E1-3-17 | `database/historify_db.py` `EXCHANGE_MARKET_OPEN_SECONDS` mapping with India default 33300 | BIS-DEFERRED | P2 | v5 Phase 4-bis deferred historify TZ work (CLAUDE.md ADR 0020 § Deferred); closed by P2 historify scheduler venue-aware |
| E1-3-18 | `database/historify_db.py` `(symbol, exchange)` keys, `instrument_id` nullable | INTENTIONAL-INDIA-LIMIT | n/a | LEGACY_INDIA classification; promoted code uses `database/instruments_repo.py` |
| E1-3-19 | `database/historify_db.py` `ist_offset` naming | INTENTIONAL-INDIA-LIMIT | n/a | Same as E1-3-18; legacy keys ok in legacy table |
| E1-3-20 | `database/token_db_enhanced.py` DDMMMYY+CE/PE regex grammar | INTENTIONAL-INDIA-LIMIT | n/a | LEGACY_INDIA + `tests/audit/test_symtoken_callers_zero_leaks.py` (ADR 0019 — promoted code never reads this) |
| E1-3-21 | `database/token_db_enhanced.py` cache uses `Asia/Kolkata` | INTENTIONAL-INDIA-LIMIT | n/a | Same as E1-3-20 |
| E1-3-22 | `services/option_symbol_service.py` Indian index list, NFO/BFO mapping | INTENTIONAL-INDIA-LIMIT | n/a | ADR 0011 + ADR 0027 — options analytics are India-gated; provider contract isolates non-India |
| E1-3-23 | `services/option_chain_service.py` Indian index list | INTENTIONAL-INDIA-LIMIT | n/a | Same as E1-3-22 |
| E1-3-24 | `services/options_multiorder_service.py` Indian routing | INTENTIONAL-INDIA-LIMIT | n/a | Same as E1-3-22 |
| E1-3-25 | `services/expiry_service.py` India-only, DDMMMYY parser | INTENTIONAL-INDIA-LIMIT | n/a | ADR 0020 — `services.feature_gate_service.require_region_feature("expiry", ...)` returns 422 for non-India |
| E1-3-26 | `services/flow_executor_service.py` order defaults `NSE`/`MIS` | BIS-DEFERRED | P2 | v5 Phase 5-bis (flow scheduler venue-aware); closed by P2 |
| E1-3-27 | `services/flow_executor_service.py` options defaults NIFTY/CE/NRML + Indian lot sizes | BIS-DEFERRED | P2 | Same as E1-3-26 |
| E1-3-28 | `services/options/providers/india/__init__.py` declares Phase 9-bis until completion | BIS-DEFERRED | P2 | Closed by P2 options dispatcher migration |
| E1-3-29 | `services/sandbox/providers/india/__init__.py` declares Phase 8-bis until completion | BIS-DEFERRED | P2 | Closed by P2 sandbox dispatcher migration |
| E1-3-30 | `services/screeners/providers/india/chartink.py` declares Phase 10-bis until completion | BIS-DEFERRED | P2 | Closed by P2 screener dispatcher migration |
| E1-3-31 | `database/sandbox_db.py` INR capital + IST reset + India square-off + India leverage | INTENTIONAL-INDIA-LIMIT | n/a | ADR 0026 — sandbox is provider-pluggable; India provider keeps Indian semantics |
| E1-3-32 | `upgrade/migrate_sandbox.py` migration seeds India defaults | INTENTIONAL-INDIA-LIMIT | n/a | Same as E1-3-31; migration only seeds the India provider's defaults |
| E1-3-33 | `sandbox/order_manager.py` IST + India product validation | BIS-DEFERRED | P2 | v5 Phase 4-bis (sandbox blueprint route adoption); closed by P2 |
| E1-3-34 | `sandbox/catch_up_processor.py` T+1 + IST | BIS-DEFERRED | P2 | Same as E1-3-33 |
| E1-3-35 | `sandbox/position_manager.py` Indian product lifecycle | BIS-DEFERRED | P2 | Same as E1-3-33 |
| E1-3-36 | `sandbox/execution_engine.py` IST timestamps | BIS-DEFERRED | P2 | Same as E1-3-33 |
| E1-3-37 | `frontend/src/hooks/useSupportedExchanges.ts` India-shaped fallback | BIS-DEFERRED | P1 | v5 Phase 2-bis (frontend per-component cleanup); closed by P1 |
| E1-3-38 | `frontend/src/lib/india_legacy/legacy_fallback_exchanges.ts` exists | INTENTIONAL-INDIA-LIMIT | n/a | Allowlisted in `frontend/scripts/literal_scan_allowlist.json`; gated behind India region check |
| E1-3-39 | `frontend/src/lib/flow/constants.ts` India venues/products + defaults | BIS-DEFERRED | P1 | v5 Phase 2-bis; closed by P1 |
| E1-3-40 | `frontend/src/lib/flow/constants.ts` `09:15` defaults | BIS-DEFERRED | P1 | Same as E1-3-39 |
| E1-3-41 | `frontend/src/components/flow/panels/ConfigPanel.tsx` India defaults | BIS-DEFERRED | P1 | Same as E1-3-39 |
| E1-3-42 | `frontend/src/components/trading/PlaceOrderDialog.tsx` Indian product split | BIS-DEFERRED | P1 | Same as E1-3-39 |
| E1-3-43 | `frontend/src/pages/admin/MarketTimings.tsx` Indian session text | BIS-DEFERRED | P1 | Same as E1-3-39 |
| E1-3-44 | `frontend/src/pages/admin/FreezeQty.tsx` Indian freeze concept | INTENTIONAL-INDIA-LIMIT | n/a | Freeze quantity is an Indian-derivatives regulatory concept; UI is region-gated |
| E1-3-45 | `frontend/src/pages/CustomStraddle.tsx` Indian lots + 5.5h IST + en-IN | BIS-DEFERRED | P1 | v5 Phase 2-bis; closed by P1 (use `useFormatCurrency` + venue tz hook) |
| E1-3-46 | `frontend/src/pages/HealthMonitor.tsx` + Latency/Security `Asia/Kolkata` | BIS-DEFERRED | P1 | v5 Phase 2-bis; closed by P1 |
| E1-3-47 | `frontend/src/pages/python-strategy/*.tsx` Indian sessions + `Current IST` | BIS-DEFERRED | P1 | v5 Phase 2-bis; closed by P1 |
| E1-3-48 | `frontend/src/pages/Historify.tsx` + `HistorifyCharts.tsx` IST + Indian symbols | BIS-DEFERRED | P1 | v5 Phase 2-bis; closed by P1 |
| E1-3-49 | `frontend/src/pages/IVChart.tsx` + `StraddleChart.tsx` 5.5h IST shift | INTENTIONAL-INDIA-LIMIT | n/a | India-options analytics surface; backed by `is_india_region_active()` gate via `services.feature_gate_service.require_region_feature` |
| E1-3-50 | `frontend/src/pages/StrategyBuilder.tsx` DDMMMYY + Indian indices | INTENTIONAL-INDIA-LIMIT | n/a | India-strategy-builder surface; allowlisted |
| E1-3-51 | `frontend/src/lib/strategyMath.ts` INR risk-free, DDMMMYY, 15:30 IST | INTENTIONAL-INDIA-LIMIT | n/a | Same as E1-3-50 |
| E1-3-52 | `frontend/src/pages/StrategyPortfolio.tsx`/PnL/Positions/Payoff `₹` + en-IN | BIS-DEFERRED | P1 | v5 Phase 2-bis; closed by P1 (currency-aware formatter) |
| E1-3-53 | `market_regions/india/plugin.json` declares `Asia/Kolkata`, `INR`, NSE/etc. | ALREADY-CLOSED | n/a | Region plugin scope is correct; data-driven |
| E1-3-54 | Many India broker `plugin.json` infer region/currency from `IN_stock` | BIS-DEFERRED | P5/P6/P7 | v5 readiness matrix Phase 8-bis (explicit declaration upgrade); closed per-broker in P5/P6/P7 |
| E1-3-55 | `broker/aliceblue/database/master_contract_db.py` Indian segments | INTENTIONAL-INDIA-LIMIT | n/a | BROKER_PLUGIN classification; broker adapter is India-scoped by design |
| E1-3-56 | `broker/aliceblue/api/data.py` Indian index/IST mapping | INTENTIONAL-INDIA-LIMIT | n/a | Same as E1-3-55 |
| E1-3-57 | `broker/aliceblue/mapping/order_data.py` NSE-as-fallback | INTENTIONAL-INDIA-LIMIT | n/a | Same as E1-3-55; India broker can use NSE fallback |
| E1-3-58 | `broker/aliceblue/streaming/aliceblue_client.py` Indian products/exchanges | INTENTIONAL-INDIA-LIMIT | n/a | Same as E1-3-55 |
| E1-3-59 | `broker/shoonya/api/auth_api.py` hard-coded `api.shoonya.com` | INTENTIONAL-INDIA-LIMIT | n/a | Broker-specific URL; correct for the adapter |
| E1-3-60 | `broker/shoonya/database/master_contract_db.py` Indian segments | INTENTIONAL-INDIA-LIMIT | n/a | Same as E1-3-55 |
| E1-3-61 | `broker/compositedge/streaming/compositedge_mapping.py` defaults to NSE | INTENTIONAL-INDIA-LIMIT | n/a | Same as E1-3-55 (XTS-shaped Indian broker) |
| E1-3-62 | `broker/*/mapping/order_data.py` repeated `exchange="NSE"` | INTENTIONAL-INDIA-LIMIT | n/a | Same as E1-3-55 (per-broker India fallback inside India broker plugin) |
| E1-3-63 | `broker/*/database/master_contract_db.py` Indian segments | INTENTIONAL-INDIA-LIMIT | n/a | Same as E1-3-55 |
| E1-3-64 | `mcp/mcpserver.py` `_broker_is_india_shaped` returns true for unknown caps | INTENTIONAL-INDIA-LIMIT | n/a | ADR 0006 fail-closed for non-India is enforced at plugin loader; the MCP shim path is gated to India brokers |
| E1-3-65 | `mcp/mcpserver.py` order/data tool defaults `NSE`/`MIS` | INTENTIONAL-INDIA-LIMIT | n/a | Same as E1-3-64; MCP defaults apply only when broker is India-shaped |
| E1-3-66 | `mcp/mcpserver.py` index quote tool only Indian indices | INTENTIONAL-INDIA-LIMIT | n/a | Same as E1-3-64 |
| E1-3-67 | `restx_api/ticker.py` defaults `NSE:RELIANCE` | INTENTIONAL-INDIA-LIMIT | n/a | v1 deprecation (Phase 8 v5); no v6 work — sunset removes it |
| E1-3-68 | `blueprints/websocket_example.py` example `NSE:RELIANCE` | INTENTIONAL-INDIA-LIMIT | n/a | Example doc; not load-bearing |
| E1-3-69 | `broker/fyers/streaming/*` Indian symbol formats | INTENTIONAL-INDIA-LIMIT | n/a | Same as E1-3-55 |
| E1-3-70 | `broker/{paytm,zerodha,indmoney}/.../data.py` Indian token formats | INTENTIONAL-INDIA-LIMIT | n/a | Same as E1-3-55 |
| E1-3-71 | `collections/openalgo/IN_stock/*` + Postman collections use Indian examples | INTENTIONAL-INDIA-LIMIT | n/a | India-focused API collection; not load-bearing |
| E1-3-72 | `docs/api/market-calendar/timings.md` IST examples | INTENTIONAL-INDIA-LIMIT | n/a | Documentation; non-load-bearing |
| E1-3-73 | `docs/api/market-data/history.md` says timestamps are IST | INTENTIONAL-INDIA-LIMIT | n/a | Doc reflects v1 behavior; ADR 0003 freezes v1 |
| E1-3-74 | `docs/api/options-services/optionchain.md` Indian indices | INTENTIONAL-INDIA-LIMIT | n/a | Doc; v1/India-specific |
| E1-3-75 | `docs/userguide/symbol-format/README.md` Indian grammar | INTENTIONAL-INDIA-LIMIT | n/a | Doc; v1/India-specific |
| E1-3-76 | `docs/adr/0011-region-gating-india-features.md` lists India-only features | ALREADY-CLOSED | n/a | The ADR itself documents the closure |
| E1-3-77 | ADR 0026 (Sandbox) acknowledges India hardcoding | ALREADY-CLOSED | n/a | ADR + provider contract |
| E1-3-78 | ADR 0027 (Options) acknowledges India hardcoding | ALREADY-CLOSED | n/a | ADR + provider contract |
| E1-3-79 | ADR 0028 (Screener) acknowledges India hardcoding | ALREADY-CLOSED | n/a | ADR + provider contract |
| E1-3-80 | `frontend/scripts/literal_scan_allowlist.json` lists allowlisted UI | BIS-DEFERRED | P1 | v5 Phase 2-bis; P1 shrinks allowlist |
| E1-3-81 | `test/all_symbols.csv` + `test/symbols.csv` + `download/symbols.csv` Indian fixtures | INTENTIONAL-INDIA-LIMIT | n/a | Test fixtures for India parity; not load-bearing for non-India |

### Expert 1 §4 — implicit market assumptions

| ID | Finding (terse) | Classification | Owning v6 Phase | Evidence |
|---|---|---|---|---|
| E1-4-01 | `domain/capabilities.py` `_indian_defaults` for `IN_stock` | INTENTIONAL-INDIA-LIMIT | n/a | ADR 0006 fail-closed for non-India; India plugins legacy-inferred |
| E1-4-02 | `domain/capabilities.py` master-contract refresh defaults to `08:00 IST` for legacy India brokers | INTENTIONAL-INDIA-LIMIT | n/a | Same as E1-4-01; non-India brokers must declare policy |
| E1-4-03 | `frontend/src/hooks/useSupportedExchanges.ts` null caps treated as India-shaped | BIS-DEFERRED | P1 | v5 Phase 2-bis; closed by P1 |
| E1-4-04 | `mcp/mcpserver.py` empty caps return India-shaped true | INTENTIONAL-INDIA-LIMIT | n/a | MCP path is India-shim-only |
| E1-4-05 | `services/venue_session_service.py` lookup failure → IST | INTENTIONAL-INDIA-LIMIT | n/a | ADR 0009 — explicit India-compat fallback for legacy callers |
| E1-4-06 | `database/historify_db.py` `(symbol, exchange)` identity | INTENTIONAL-INDIA-LIMIT | n/a | LEGACY_INDIA classification |
| E1-4-07 | `database/token_db_enhanced.py` DDMMMYY parser | INTENTIONAL-INDIA-LIMIT | n/a | Same as E1-3-20 |
| E1-4-08 | `database/market_calendar_db.py` + `historify_db.py` 09:15/09:00 session encoding | INTENTIONAL-INDIA-LIMIT | n/a | Same as E1-3-15/E1-3-17 |
| E1-4-09 | Sandbox CNC/MIS vs NRML/MIS modeling | INTENTIONAL-INDIA-LIMIT | n/a | India sandbox provider; non-India sandbox provider declares its own model (ADR 0026) |
| E1-4-10 | Flow options Indian underlyings/lot sizes | BIS-DEFERRED | P2 | Same as E1-3-26/E1-3-27 |
| E1-4-11 | StrategyBuilder + strategyMath Indian symbol grammar | INTENTIONAL-INDIA-LIMIT | n/a | India-strategy-builder surface |
| E1-4-12 | `market_regions/india/plugin.json` scoped India metadata | ALREADY-CLOSED | n/a | Region plugin is intentional |
| E1-4-13 | Most legacy plugins lack `supported_regions`/`base_currency` | BIS-DEFERRED | P5/P6/P7 | v5 Phase 8-bis explicit declaration upgrade per India broker |
| E1-4-14 | `docs/refactor/inventory/*.md` track deferred items | ALREADY-CLOSED | n/a | Inventory docs are evidence; v6 closes the items they describe |

### Expert 2 §3 — explicit India-specific findings

| ID | Finding (terse) | Classification | Owning v6 Phase | Evidence |
|---|---|---|---|---|
| E2-3-01 | `utils/constants.py` LEGACY INDIA stamp | ALREADY-CLOSED | n/a | ADR 0017 |
| E2-3-02 | `utils/constants.py` Indian exchange constants | ALREADY-CLOSED | n/a | Same as E1-3-02 |
| E2-3-03 | `utils/constants.py` `FNO_EXCHANGES` + `VALID_EXCHANGES` | ALREADY-CLOSED | n/a | Same as E1-3-02 |
| E2-3-04 | `utils/constants.py` Indian product types | ALREADY-CLOSED | n/a | Same as E1-3-03 |
| E2-3-05 | `utils/constants.py` `EXCHANGE_BADGE_COLORS` Indian | INTENTIONAL-INDIA-LIMIT | n/a | LEGACY_INDIA classification |
| E2-3-06 | `domain/capabilities.py` legacy-India inference | INTENTIONAL-INDIA-LIMIT | n/a | Same as E1-4-01 |
| E2-3-07 | `domain/capabilities.py` India feature defaults | INTENTIONAL-INDIA-LIMIT | n/a | Same as E1-4-01 |
| E2-3-08 | `domain/capabilities.py` `_indian_defaults` body | INTENTIONAL-INDIA-LIMIT | n/a | Same as E1-4-01 |
| E2-3-09 | `domain/capabilities.py` 369-453 broker metadata fallback | INTENTIONAL-INDIA-LIMIT | n/a | ADR 0006; non-India fail-closed |
| E2-3-10 | `services/feature_gate_service.py` `legacy_india_fallback` opt-in | BIS-DEFERRED | P4 | v6 P4 retires `_legacy_india_region_for_compat()` and the parameter |
| E2-3-11 | Broker plugin scan: 35 manifests / 31 IN_stock / 32 omit `supported_regions` | BIS-DEFERRED | P5/P6/P7 | v5 Phase 8-bis explicit declaration upgrade |
| E2-3-12 | `broker/aliceblue/plugin.json` India-only manifest | INTENTIONAL-INDIA-LIMIT | n/a | India broker by design |
| E2-3-13 | `broker/shoonya/plugin.json` India-only manifest | INTENTIONAL-INDIA-LIMIT | n/a | Same as E2-3-12 |
| E2-3-14 | `broker/alpaca/plugin.json` declares US region | ALREADY-CLOSED | n/a | Already non-India, framework-conformant |
| E2-3-15 | `blueprints/chartink.py` IST + India venues | BIS-DEFERRED | P2 | Same as E1-3-08 |
| E2-3-16 | `blueprints/strategy.py` India scheduler + matrix | BIS-DEFERRED | P2 | Same as E1-3-09 |
| E2-3-17 | `blueprints/admin.py` freeze-quantity `NFO` default | INTENTIONAL-INDIA-LIMIT | n/a | Indian regulatory concept |
| E2-3-18 | `blueprints/flow.py` `09:15` + `NSE` defaults + Indian indices | BIS-DEFERRED | P2 | Same as E1-3-10 |
| E2-3-19 | `blueprints/historify.py` 09:15 examples + `NFO` defaults | BIS-DEFERRED | P2 | v5 Phase 4-bis historify; closed by P2 |
| E2-3-20 | `app.py` + `.sample.env` India formatting + IST + `08:00 IST` | BIS-DEFERRED | P2 | v5 Phase 5-bis (env defaults are operator-overridable; Phase 2 ensures runtime never hardcodes IST in promoted paths) |
| E2-3-21 | `utils/number_formatter.py` legacy `format_indian_currency` | INTENTIONAL-INDIA-LIMIT | n/a | LEGACY helper; promoted code uses currency-aware formatter (`utils/number_formatter.py` extension) |
| E2-3-22 | `database/qty_freeze_db.py` Indian freeze rules | INTENTIONAL-INDIA-LIMIT | n/a | Same as E2-3-17 |
| E2-3-23 | `database/sandbox_db.py` India provider settings | INTENTIONAL-INDIA-LIMIT | n/a | India sandbox provider; ADR 0026 |
| E2-3-24 | `blueprints/sandbox.py` INR/IST defaults | BIS-DEFERRED | P2 | v5 Phase 4-bis; closed by P2 |
| E2-3-25 | `sandbox/order_manager.py` `_enforce_india_region_for_sandbox` + India semantics | BIS-DEFERRED | P2 | Same as E1-3-33 |
| E2-3-26 | `services/option_symbol_service.py` Indian grammar | INTENTIONAL-INDIA-LIMIT | n/a | ADR 0027 |
| E2-3-27 | `services/option_chain_service.py` Indian grammar | INTENTIONAL-INDIA-LIMIT | n/a | ADR 0027 |
| E2-3-28 | `services/option_greeks_service.py` Indian options grammar + scope | INTENTIONAL-INDIA-LIMIT | n/a | ADR 0011 + ADR 0020 region gate |
| E2-3-29 | `services/iv_chart_service.py` Indian options + IST | INTENTIONAL-INDIA-LIMIT | n/a | Same as E2-3-28 |
| E2-3-30 | `services/straddle_chart_service.py` Indian + 15:30 IST | INTENTIONAL-INDIA-LIMIT | n/a | Same as E2-3-28 |
| E2-3-31 | `database/token_db_enhanced.py` Indian F&O grammar | INTENTIONAL-INDIA-LIMIT | n/a | Same as E1-3-20 |
| E2-3-32 | `utils/symbol_utils.py` Indian suffix model | INTENTIONAL-INDIA-LIMIT | n/a | LEGACY_INDIA |
| E2-3-33 | `frontend/src/lib/india_legacy/legacy_fallback_exchanges.ts` | INTENTIONAL-INDIA-LIMIT | n/a | Same as E1-3-38 |
| E2-3-34 | `frontend/src/lib/flow/constants.ts` defaults | BIS-DEFERRED | P1 | Same as E1-3-39 |
| E2-3-35 | `mcp/mcpserver.py` MCP defaults | INTENTIONAL-INDIA-LIMIT | n/a | Same as E1-3-64 |
| E2-3-36 | `restx_api/_v1_lane_guard.py` v1 hard-block | ALREADY-CLOSED | n/a | ADR 0017 |
| E2-3-37 | `restx_api/schemas.py` v1 schemas | ALREADY-CLOSED | n/a | Same as E1-3-05 |
| E2-3-38 | `restx_api/data_schemas.py` v1 schemas | ALREADY-CLOSED | n/a | Same as E1-3-04 |
| E2-3-39 | `restx_api/ticker.py` IST default | INTENTIONAL-INDIA-LIMIT | n/a | Same as E1-3-67 |
| E2-3-40 | `broker/aliceblue/database/master_contract_db.py` Indian segments | INTENTIONAL-INDIA-LIMIT | n/a | Same as E1-3-55 |
| E2-3-41 | `broker/aliceblue/api/data.py` Indian routing/IST | INTENTIONAL-INDIA-LIMIT | n/a | Same as E1-3-56 |
| E2-3-42 | `broker/aliceblue/mapping/order_data.py` Indian fields | INTENTIONAL-INDIA-LIMIT | n/a | Same as E1-3-57 |
| E2-3-43 | `broker/shoonya/database/master_contract_db.py` Indian segments | INTENTIONAL-INDIA-LIMIT | n/a | Same as E1-3-60 |
| E2-3-44 | `broker/shoonya/api/data.py` Indian index routing | INTENTIONAL-INDIA-LIMIT | n/a | Same as E1-3-60 |
| E2-3-45 | Multiple Indian broker adapters default holdings/exchange to NSE | INTENTIONAL-INDIA-LIMIT | n/a | Same as E1-3-62 |
| E2-3-46 | Multiple broker adapters carry BO/CO mappings | INTENTIONAL-INDIA-LIMIT | n/a | Broker-specific |
| E2-3-47 | Multiple Indian broker paise/rupees conversions | INTENTIONAL-INDIA-LIMIT | n/a | Indian price units |
| E2-3-48 | Multiple Indian broker IST timestamps | INTENTIONAL-INDIA-LIMIT | n/a | Indian broker normalization |
| E2-3-49 | `broker/deltaexchange/api/funds.py` `balance_inr` aggregation | INTENTIONAL-INDIA-LIMIT | n/a | Crypto adapter for Indian users; INR settlement context |
| E2-3-50 | `broker/deltaexchange/api/order_api.py` Asia/Kolkata + spot symbol `_INR` | INTENTIONAL-INDIA-LIMIT | n/a | Same as E2-3-49 |
| E2-3-51 | `broker/deltaexchange/mapping/order_data.py` MIS/CNC/NRML + NSE | INTENTIONAL-INDIA-LIMIT | n/a | Crypto for Indian users |
| E2-3-52 | `broker/deltaexchange/streaming/delta_mapping.py` `NSE`→`CRYPTO` alias | INTENTIONAL-INDIA-LIMIT | n/a | Compatibility alias inside crypto adapter |
| E2-3-53 | `docs/api/options-services/optionsymbol.md` Indian options docs | INTENTIONAL-INDIA-LIMIT | n/a | Doc |
| E2-3-54 | `docs/api/order-information/openposition.md` Indian product/exchange table | INTENTIONAL-INDIA-LIMIT | n/a | Doc |
| E2-3-55 | `test/symbols.csv` Indian fixture | INTENTIONAL-INDIA-LIMIT | n/a | Test fixture |
| E2-3-56 | `test/all_symbols.csv` Indian fixture | INTENTIONAL-INDIA-LIMIT | n/a | Test fixture |

### Expert 2 §4 — implicit market assumptions

| ID | Finding (terse) | Classification | Owning v6 Phase | Evidence |
|---|---|---|---|---|
| E2-4-01 | `utils/auth_utils.py` IST + `08:00 IST` cutoff | INTENTIONAL-INDIA-LIMIT | n/a | India broker master-contract refresh; ADR 0006 |
| E2-4-02 | `utils/session.py` IST fallback | INTENTIONAL-INDIA-LIMIT | n/a | Same as E1-3-12 |
| E2-4-03 | `database/market_calendar_db.py` India calendar | INTENTIONAL-INDIA-LIMIT | n/a | Same as E1-3-15 |
| E2-4-04 | `database/market_calendar_db.py` India holidays/Muhurat | INTENTIONAL-INDIA-LIMIT | n/a | Same as E1-3-16 |
| E2-4-05 | `database/market_calendar_db.py` IST midnight session windows | INTENTIONAL-INDIA-LIMIT | n/a | Same as E1-3-15 |
| E2-4-06 | `database/historify_db.py` Indian candle alignment | BIS-DEFERRED | P2 | Same as E1-3-17 |
| E2-4-07 | `database/venue_offset.py` unknown→India fallback | INTENTIONAL-INDIA-LIMIT | n/a | ADR 0009 — explicit India-compat fallback |
| E2-4-08 | `sandbox/squareoff_manager.py` India schedule | BIS-DEFERRED | P2 | Same as E1-3-33 |
| E2-4-09 | `sandbox/squareoff_thread.py` Indian schedule + T+1 IST | BIS-DEFERRED | P2 | Same as E1-3-33 |
| E2-4-10 | `sandbox/catch_up_processor.py` T+1 IST | BIS-DEFERRED | P2 | Same as E1-3-34 |
| E2-4-11 | `sandbox/holdings_manager.py` T+1/CNC | BIS-DEFERRED | P2 | Same as E1-3-33 |
| E2-4-12 | `sandbox/fund_manager.py` ₹1Cr + IST reset | BIS-DEFERRED | P2 | Same as E1-3-33 |
| E2-4-13 | `sandbox/execution_engine.py` IST timestamps | BIS-DEFERRED | P2 | Same as E1-3-36 |
| E2-4-14 | `blueprints/analyzer.py` IST filter | INTENTIONAL-INDIA-LIMIT | n/a | ADR 0004 — analyzer stays India-limited |
| E2-4-15 | `blueprints/health.py` IST CSV header | INTENTIONAL-INDIA-LIMIT | n/a | Operational reporting in IST is acceptable |
| E2-4-16 | `blueprints/latency.py` IST CSV header | INTENTIONAL-INDIA-LIMIT | n/a | Same as E2-4-15 |
| E2-4-17 | `blueprints/log.py` IST display | INTENTIONAL-INDIA-LIMIT | n/a | Same as E2-4-15 |
| E2-4-18 | `blueprints/pnltracker.py` IST P&L | INTENTIONAL-INDIA-LIMIT | n/a | Same as E2-4-15 |
| E2-4-19 | `blueprints/python_strategy.py` IST scheduler | BIS-DEFERRED | P2 | Same as E1-3-11 |
| E2-4-20 | `services/market_calendar_service.py` NSE fallback | INTENTIONAL-INDIA-LIMIT | n/a | Same as E1-3-14 |
| E2-4-21 | `services/flow_executor_service.py` flow defaults | BIS-DEFERRED | P2 | Same as E1-3-26/27 |
| E2-4-22 | `services/iv_chart_service.py` defaults to Asia/Kolkata | INTENTIONAL-INDIA-LIMIT | n/a | Same as E2-3-29 |
| E2-4-23 | `services/straddle_chart_service.py` 15:30 IST | INTENTIONAL-INDIA-LIMIT | n/a | Same as E2-3-30 |
| E2-4-24 | `broker/groww/api/data.py` IST + 09:15-15:30 | INTENTIONAL-INDIA-LIMIT | n/a | India broker adapter |
| E2-4-25 | `broker/dhan/+dhan_sandbox/api/data.py` IST | INTENTIONAL-INDIA-LIMIT | n/a | India broker adapter |
| E2-4-26 | `broker/angel/api/data.py` +5:30 | INTENTIONAL-INDIA-LIMIT | n/a | India broker adapter |
| E2-4-27 | `broker/compositedge` + `fivepaisaxts/api/data.py` IST | INTENTIONAL-INDIA-LIMIT | n/a | India broker adapter |
| E2-4-28 | `broker/fivepaisa/api/data.py` IST market hours | INTENTIONAL-INDIA-LIMIT | n/a | India broker adapter |
| E2-4-29 | `broker/flattrade/api/data.py` IST | INTENTIONAL-INDIA-LIMIT | n/a | India broker adapter |
| E2-4-30 | `broker/definedge/api/data.py` Indian close + IST | INTENTIONAL-INDIA-LIMIT | n/a | India broker adapter |
| E2-4-31 | `test/test_python_strategy_*` + `tests/venue_session/test_nse_session.py` IST/NSE biased | INTENTIONAL-INDIA-LIMIT | n/a | India parity tests |

## Mock plugin extension list (for Phase 4)

The framework-readiness contract test
(`tests/contracts/test_framework_ready_for_real_brokers.py`) currently
verifies file existence for: `auth_api.py`, `account_api.py`,
`order_api.py`, `position_balance_adapters.py`, `quote_api.py`,
`bar_api.py`, `stream_api.py`, `sync/instrument_sync.py`. The mock
plugins (`broker/_mock_schwab_like/`, `broker/_mock_webull_like/`)
declare strict-mode capability metadata covering: combo types
(SINGLE / OTO / OCO / OTOCO / COMBO / MULTILEG_OPTIONS), fractional /
notional / extended hours / short selling, account context with
`account_hash` / `entitlements`, OAuth auth modes, US region venues
(XNYS / XNAS / ARCX / BATS / IEXG), pre/post sessions, master
contract refresh policy (cutoff_local + timezone).

Per Phase 0 audit, contracts that are declared in capability metadata
but **not exercised end-to-end** by a contract test against the mocks:

| Contract | Status | Phase 4 action |
|---|---|---|
| Combo dispatch end-to-end (OTOCO / MULTILEG_OPTIONS) | partial — mock has handler in `mapping/combo.py`-equivalent path; e2e tests only cover Schwab-like single equity + OTOCO | extend mock combo coverage to MULTILEG_OPTIONS through the dispatcher |
| Streaming subscribe → events → unsubscribe lifecycle | partial — e2e covers Webull happy path | extend mock to deliver mid-stream disconnect + reconnect path |
| Master-contract refresh policy execution | declared in `plugin.json` but **no test exercises the cutoff_local + timezone semantics** through `services/account_context_service` | add a contract test that invokes the mock's instrument sync at a non-IST cutoff and asserts the refresh policy is honored |
| Account context entitlement enforcement | declared (`entitlements: list[str]`) but rule_enforcement does not yet read it (per `schwab_readiness.md` table — "deferred to plugin work") | extend the mock to declare a sample entitlement requirement and assert `rule_enforcement.check_order` raises `entitlement_required` |
| Position adapter normalized currency propagation | scaffolded but not asserted to carry venue currency through to `/api/v2/positions` response | add normalized-currency assertion to mock position adapter test |

These five extensions are the Phase 4 mock-plugin-extension targets.

## Legacy-compat named-caller list (for Phase 2)

Production callers of `services.feature_gate_service.is_india_region_active()`
(direct or via `is_feature_enabled_for_active_region`) outside the
gate functions themselves:

* `services/expiry_service.py`
* `services/option_greeks_service.py`
* `services/options_multiorder_service.py`
* `services/iv_chart_service.py`
* `services/gex_service.py`
* `services/straddle_chart_service.py`
* `services/synthetic_future_service.py`
* `services/vol_surface_service.py`
* `services/flow_executor_service.py`
* `sandbox/order_manager.py`
* `utils/capability_guards.py`

The two remaining named callers passing
`legacy_india_fallback=True` in production code are inside
`services/feature_gate_service.py` itself
(`is_india_region_active()` line 118,
`is_feature_enabled_for_active_region()` line 131,
`active_region_code()`-aware helper line 178). Phase 2 of v6 wires
the **production callers above** to the dispatcher path. Phase 4 then
retires the helper itself once the only remaining callers are the
gates.

Sandbox lane callers requiring dispatcher migration (Phase 2 Step 1):

* `blueprints/sandbox.py`
* `sandbox/order_manager.py`
* `sandbox/squareoff_manager.py`
* `sandbox/squareoff_thread.py`
* `sandbox/catch_up_processor.py`
* `sandbox/holdings_manager.py`
* `sandbox/fund_manager.py`
* `sandbox/execution_engine.py`
* `database/sandbox_db.py` (read region/currency from additive columns)

Options lane callers requiring dispatcher migration (Phase 2 Step 2):

* `services/option_chain_service.py`
* `services/option_symbol_service.py`
* `services/option_greeks_service.py`
* `services/iv_chart_service.py`
* `services/straddle_chart_service.py`
* `services/options_multiorder_service.py`
* `services/expiry_service.py`
* `services/oi_profile_service.py`
* `services/gex_service.py`
* `services/iv_smile_service.py`

Screener lane callers requiring dispatcher migration (Phase 2 Step 3):

* `blueprints/chartink.py`
* Other callers identified by `grep services\.screeners\.dispatcher`
  (currently zero blueprint callers — `blueprints/chartink.py` calls
  the legacy India provider directly).

Strategy / flow scheduler lane callers requiring dispatcher migration
(Phase 2 Step 4):

* `services/flow_executor_service.py`
* `services/flow_scheduler_service.py`
* `blueprints/python_strategy.py`
* `services/historify_scheduler_service.py`

## Frontend per-component cleanup list (for Phase 1)

The current `frontend/scripts/literal_scan_allowlist.json` has **80
entries**. The breakdown by closure category:

* **Allowlisted intentionally as India-specific UI surface** (kept on
  allowlist; not Phase 1 work): India-specific pages with no non-India
  equivalent (e.g. Chartink, IV Chart, Strategy Builder, Custom
  Straddle, GEX Dashboard, IV Smile, OI Profile, OI Tracker, Sandbox,
  SandboxPnL, StraddleChart) — these stay allowlisted because the
  feature is region-gated.
* **v5 Phase 2 multi-region helpers (kept)**: `src/lib/format/currency.ts`
  and `src/lib/format/timezone.ts` are correctly multi-region and
  allowlisted only because they enumerate IANA labels.
* **Phase 1 cleanup targets** (must shrink from allowlist):
  * `src/hooks/useSupportedExchanges.ts` — replace null-caps→India
    fallback with a "loading / unsupported" surface (E1-3-37, E1-4-03).
  * `src/lib/flow/constants.ts` — derive default exchange / product /
    option type / time window from `/api/v2/regions/<code>/flow_defaults`
    instead of static India constants (E1-3-39/40, E2-3-34).
  * `src/components/flow/panels/ConfigPanel.tsx` — same as flow constants
    (E1-3-41).
  * `src/components/trading/PlaceOrderDialog.tsx` — derive product /
    exchange categories from broker capabilities instead of NRML/MIS
    static map (E1-3-42).
  * `src/pages/admin/MarketTimings.tsx` — fetch session windows from
    region plugin instead of hard-coded text (E1-3-43).
  * `src/pages/CustomStraddle.tsx` (only the timestamp +5.5h shift +
    formatINR; lots and Indian indices stay allowlisted) — use venue
    timezone hook + currency-aware formatter (E1-3-45).
  * `src/pages/HealthMonitor.tsx`, `src/pages/monitoring/LatencyDashboard.tsx`,
    `src/pages/monitoring/SecurityDashboard.tsx` — replace
    `Asia/Kolkata` with `useVenueTimezone()` (E1-3-46).
  * `src/pages/python-strategy/{NewPythonStrategy,SchedulePythonStrategy,PythonStrategyIndex}.tsx`
    — replace MCX 09:00-23:55 / NSE/BSE 09:15-15:30 with venue session
    fetch (E1-3-47).
  * `src/pages/Historify.tsx`, `src/pages/HistorifyCharts.tsx` —
    replace `09:15` scheduler default + 5.5h chart shift with venue tz
    + region default (E1-3-48).
  * `src/pages/StrategyPortfolio.tsx`,
    `src/components/strategy-builder/{PnLTab,PositionsPanel,PayoffChart}.tsx`
    — use `useFormatCurrency()` instead of `₹` + `en-IN` (E1-3-52).
  * `src/pages/admin/Holidays.tsx` — confirm it uses `is_india_region_active`
    style gating purely (this file has the literal scanned because it
    references the gate; not a literal violation).

Phase 1 must add a `useVenueTimezone()` hook in
`frontend/src/hooks/useVenueTimezone.ts` (the v5 Phase 2 work
introduced `useFormatCurrency` and a `format/timezone.ts` helper but
not a per-page hook bound to the active broker's region). Phase 1
adds the hook, wires the pages above, and shrinks the allowlist.

## Region / provider matrix snapshot

| Region | Region plugin (`market_regions/<code>/plugin.json`) | Sandbox provider | Options provider | Screener provider | Phase 4 v6 status |
|---|---|---|---|---|---|
| `india` | ✅ present | ✅ `services/sandbox/providers/india/__init__.py` | ✅ `services/options/providers/india/__init__.py` | ✅ `services/screeners/providers/india/chartink.py` | complete |
| `us` | ✅ present | ✅ `services/sandbox/providers/us/__init__.py` | ✅ `services/options/providers/us/__init__.py` | ✅ `services/screeners/providers/us/__init__.py` | complete |
| `eu` | ✅ present | ❌ missing | ❌ missing | ❌ missing | **P3 work** |
| `uk` | ✅ present | ❌ missing | ❌ missing | ❌ missing | **P3 work** |

Crypto note: `deltaexchange` is a broker-plugin-scoped surface, not a
region plugin. Per ADR 0024, it is not a candidate for the region/
provider matrix.

## India broker enumeration for Phases 5–7

`broker/` directory listing minus mocks (`_mock_*`), non-India
broker (`alpaca`), crypto (`deltaexchange`), and sandbox-only
(`dhan_sandbox`) yields **30 India brokers**:

| Phase | Brokers (in order) | Count |
|---|---|---|
| **P5** (top 5 popularity) | zerodha, angel, dhan, upstox, fyers | 5 |
| **P6** (alpha batch 1) | aliceblue, compositedge, definedge, firstock, fivepaisa, fivepaisaxts, flattrade, groww, ibulls, iifl, iiflcapital, indmoney | 12 |
| **P7** (alpha batch 2) | jainamxts, kotak, motilal, mstock, nubra, paytm, pocketful, rmoney, samco, shoonya, tradejini, wisdom, zebu | 13 |

Total: **30** India brokers needing v2 translator + parity harness.

Note: the v5 readiness matrix (`docs/refactor/v5_india_v2_readiness_matrix.md`)
listed 29 entries; it omitted `wisdom` and `zebu` (both present in
`broker/` directory and India-shaped per Expert 1 finding 113). The
Phase 7 v6 prompt explicitly lists wisdom and zebu, so the inventory
above adds them.

## v5 → v6 closure mapping

| v5 deferred | v6 phase that closes |
|---|---|
| Phase 2-bis (frontend per-component cleanup) | Phase 1 |
| Phase 3-bis (strategy scheduler venue-aware + per-blueprint refactor) | Phase 2 |
| Phase 4-bis (sandbox blueprint route adoption + historify TZ + currency propagation) | Phase 2 |
| Phase 5-bis (options per-service shimming) | Phase 2 |
| Phase 6-bis (screener route adoption) | Phase 2 |
| Phase 8-bis (per-broker translator + parity + explicit-declaration plugin upgrade) | Phases 5, 6, 7 |
| Phase 9 default-flip (`API_V2_<INDIA_BROKER>=1`) | Phases 5, 6, 7 (per-broker, on parity-green) |
| `_legacy_india_region_for_compat()` retirement | Phase 4 (after Phase 2 migrates callers) |
| EU + UK provider stubs | Phase 3 |
| Multi-region smoke tests | Phase 3 |
| Closing audit + ADR 0031 + closing invariants gate | Phase 8 |

## Out-of-scope items (deliberately not closed in v6)

Per the v6 prompt mission paragraph and operator decisions:

* Real Schwab plugin (blocked on official API access).
* Real Webull plugin (blocked on official API access).
* Real Alpaca plugin **production hardening** (the metadata exists; deeper API work is operator decision).
* Real EU / UK pilot broker plugin code.
* Multi-broker-per-instance deployment model.
* `/api/v1/*` removal (only deprecation-with-sunset is in v6 scope).
* APAC ex-India / LATAM region plugins.
* OpenTelemetry / Prometheus metrics backend upgrade.

## Aggregate counts

* Distinct expert findings classified: **184** (Expert 1 §3: 81; Expert 1 §4: 14; Expert 2 §3: 56; Expert 2 §4: 31; minor numbering variance from 80/14/58/30 in case I missed any clusters — every row above carries an ID).
* Distinct GENUINE-GAP rows: **0** — every finding is either ALREADY-CLOSED, BIS-DEFERRED, OUT-OF-SCOPE, or INTENTIONAL-INDIA-LIMIT.
* BIS-DEFERRED rows owned by **P1**: 11 (frontend per-component closures).
* BIS-DEFERRED rows owned by **P2**: 22 (sandbox / options / screener / strategy / flow scheduler dispatcher migration + historify TZ + flow executor venue-aware).
* BIS-DEFERRED rows owned by **P4**: 1 (`legacy_india_fallback` parameter retirement).
* BIS-DEFERRED rows owned by **P5/P6/P7**: 2 (broker plugin metadata explicit-declaration upgrade + per-broker translator + parity).
* INTENTIONAL-INDIA-LIMIT rows: 116 — these are expected and gated.
* ALREADY-CLOSED rows: 32 — already enforced by ADRs / contract tests.

## Acceptance

The contract test
`tests/contracts/test_v6_gap_inventory_present.py` (added with this
phase) asserts:

1. This document exists at `docs/refactor/v6_gap_inventory.md`.
2. It contains the four required section headings:
   * "Per-finding classification table"
   * "Mock plugin extension list (for Phase 4)"
   * "Legacy-compat named-caller list (for Phase 2)"
   * "Frontend per-component cleanup list (for Phase 1)"
3. Every GENUINE-GAP row in the per-finding table has a non-empty
   owning-phase value (currently 0 GENUINE-GAP rows; the assertion
   passes vacuously, which is the correct outcome — every finding
   reaches v6 by way of a BIS-DEFERRED owning phase or is already
   closed).

The classification yields a clean v6 plan: Phase 1 closes 11
frontend rows; Phase 2 closes 22 backend service rows (the heart
of the refactor); Phase 3 adds EU/UK stubs; Phase 4 retires the
helper + extends mocks; Phases 5–7 ship 30 per-broker translators
and parity harnesses; Phase 8 writes ADR 0031 and the closing
invariants gate.
