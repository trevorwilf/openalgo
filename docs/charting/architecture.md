# Premier Charting System architecture

Region-agnostic chart workspace mounted at `/charts`. Built on three
engine options (Lightweight Charts, KLineChart Pro, optional
TradingView Advanced Charts), one Python datafeed, one Valkey-backed
live-tick pipeline, and a strict client-side / server-side safety
harness for chart-originated order entry.

## Engine-adapter pattern (P-02)

```
ChartCell ─→ loader.loadEngine(engineId)
                ├─ "lightweight"          → LightweightAdapter (default)
                ├─ "klinechart_pro"       → KLineChartProAdapter
                └─ "tradingview_advanced" → AdvancedChartsStubAdapter
                                            (fallback to Lightweight when SDK absent)
```

The loader is the **only** module under `frontend/src/charts/*` that
maps an engine string to an adapter. Components import the loader,
never an adapter directly. The loader uses dynamic `import()` so the
static bundle stays clean even when `frontend/private/tradingview/`
is empty (see HANDOFF §0.3 + `LICENSES.md`).

Adapters implement the `ChartEngineAdapter` interface from Phase 2:
mount/unmount, setBars/appendBar/updateForming, addIndicator/
removeIndicator, addDrawing/removeDrawing, setTheme, resize, plus
serializeState/restoreState for persistence and getPriceCoordinate/
getTimeCoordinate for the order-entry HUD.

## Datafeed contract (HANDOFF §0.5)

| Layer | Shape |
|---|---|
| HTTP bar | `{ t: int (UTC seconds), o, h, l, c, v: Decimal-as-string, oi: Decimal-as-string|null }` |
| HTTP quote | `{ t, bid, ask, last, bid_size, ask_size, last_size, volume_today }` |
| WS tick | `{ kind: "trade"|"quote"|"bar_forming"|"bar_closed", symbol, t: int (UTC ms), payload }` |
| WS envelope | `{ type, subscription_id, ts, payload }` |

Branded TS types (`UTCSeconds` / `UTCMillis`) prevent unit mix-ups.
Decimal fields ride as strings end-to-end.

## Live pipeline

```
Broker stream                                Tick publisher
(Alpaca WS, etc.)        →                   (subscribes via
                                              BrokerMarketDataStream
                                              from broker_streaming_registry)
                                                    │
                                                    ▼
Bar aggregator        ←   Trade ticks      ─→   Valkey
(per (symbol,                                    pubsub:ticks:<symbol>
 timeframe))          ─→  Forming bars     ─→   bar:forming:<symbol>:<tf>
                      ─→  Closed bars      ─→   bars:tail:<symbol>:<tf>
                                                    │
                                                    ▼
talipp live              SocketIO fan-out      ChartCell adapter
indicator service        /charts/streaming     (LightweightAdapter /
                         (services/charts/      KLineChartProAdapter)
                          ws_fanout.py)
```

* HANDOFF Phase 4 acceptance gates: tick at Valkey within 50ms;
  bar-update render <200ms p50; sustained 100 ticks/sec on 4-cell.
* WebSocket reconnect with exponential backoff is in the underlying
  `AlpacaWebSocketClient`. The `/charts/streaming` namespace's
  `last_seen_ts` resume hook lets the server backfill any missed
  bars after a reconnect.

## Safety harness (Phase 6 — Critical-severity)

```
Click chart                  →  OrderEntryHUD (panel)
                                  │ qty, price, side, type
                                  ▼
                                Review (idempotency token issued)
                                  │ NO Enter auto-confirm
                                  ▼
                                Confirm click only
                                  │
                                  ▼
                              client-side guards
                                  │ kill switch ON  → block
                                  │ live mode OFF  → block
                                  ▼
                              POST /api/v2/orders
                                  │
                                  ▼
                              services/charts/pre_trade_validator
                                  │ idempotency dedupe (5-min window)
                                  │ max-size guard
                                  │ max-notional guard (currency-aware)
                                  │ kill-switch state
                                  │ account context
                                  │ live-mode gate
                                  ▼
                              broker submission
                                  │
                                  ▼
                              audit_log_chart_orders row
                              (DELETE blocked at DB level — Q-17)
```

D-04: paper-only by default. D-05: max_order_size=100,
max_notional_usd=$100k, max_notional_inr=₹10L, kill_switch_default=
OFF. The "I understand the risks" 3-checkbox gate in
`RiskControlPanel` is the only path to live mode; toggling kill-
switch ON resets `live_mode_enabled` to false.

## Two-tree separation (P-04)

```
frontend/src/charts/display/       frontend/src/charts/execution/
─ OrderOverlayLayer                 ─ OrderEntryHUD
─ StrategySignalLayer               ─ OrderModifyDrag
                                    ─ OrderCancel
        ↑                                       ↑
        │ subscribes to                          │ emits
        │ /api/v2/{orders,positions,trades}     │ POST /api/v2/orders
        │ /api/v2/strategy-signals              │
        │                                       │
        └──── domain events + order IDs only ───┘
```

The two trees share no mutable state. The contract test
`tests/contracts/test_display_execution_separation.py` asserts via
static-source inspection that neither tree imports the other.

## Persistence

| Table | Owner | Purpose |
|---|---|---|
| `chart_workspace_layouts` | Phase 1 | Per-user named layouts; `cells_json` carries tabs/cells/theme. |
| `chart_drawings` | Phase 1 | One row per drawing; engine-agnostic `params_json`. |
| `chart_indicators` | Phase 1 | One row per indicator; catalog-validated `indicator_key`. |
| `chart_watchlists` | Phase 1 | Sidebar watchlists; symbols in JSON array. |
| `chart_templates` | Phase 1 | Reusable layout templates. |
| `chart_workspace_active` | Phase 1 | Per-user active-layout pointer. |
| `audit_log_chart_orders` | Phase 1 | Append-only audit (DELETE blocked, Q-17). |
| `chart_strategy_signals` | Phase 1 | External strategy signal markers. |
| `chart_safety_settings` | Phase 1 (Phase 6 wires) | Per-(user, account) safety guardrails. |

The legacy `chart_preferences` table is preserved untouched.

## Visual regression

Deferred to Phase 9+ per HANDOFF §19 / O-11. Phase 8 ships
performance-perf benchmarks (9 perf gates) but no pixel-diff tests.
The functional-correctness contract is held by the Playwright suite
in `frontend/e2e/charts/*.spec.ts`.

## Cross-references

* HANDOFF §0.3 — engine selection decision tree
* HANDOFF §0.4 — files/paths to never modify
* HANDOFF §0.5 — datafeed contracts (HTTP + WS + Valkey keys)
* HANDOFF §13.2 — streaming reconnect 7-scenario suite
* HANDOFF §13.3 — order-entry safety 8-scenario suite
* HANDOFF §14 — performance benchmark suite (9 gates)
* `frontend/LICENSES.md` — license / attribution table
* `docs/charting/legacy_vs_new.md` — operator-facing legacy map
* `docs/charting/coding_rules.md` — forbidden-pattern reference
