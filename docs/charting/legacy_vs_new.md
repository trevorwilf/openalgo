# Legacy charts vs the new `/charts` workspace

OpenAlgo's chart story is split across two non-overlapping surfaces.
This document is the operator-facing map.

## TL;DR

| Surface | Path | Scope | Region |
|---|---|---|---|
| **Legacy India charts** | various pages under `india_legacy/*` | India-specific charts (Historify, IV, OI, GEX, Straddle, Chartink, etc.). Frozen — bug fixes + compliance only. | `<IndiaOnly>` wrapper |
| **New chart workspace** | `/charts` | Region-agnostic; built on the engine-adapter pattern (Lightweight Charts + KLineChart Pro + optional TradingView Advanced Charts). | All authenticated brokers |

The two surfaces share **no** code paths. The new workspace lives
under `frontend/src/charts/*` and consumes `/api/v2/chart/*` and
`/api/v2/bars` / `/api/v2/quotes` / `/api/v2/streaming`. The legacy
pages stay on `/historify/api/data` and `/api/v1/chart` and continue
to work bit-identically.

## Frontend page-level table

These are the legacy frontend pages. Phase 7 asserts via
`tests/contracts/test_legacy_paths_unmodified.py` that **none** of
these files have changed since the merge-base of `dev` and `main`.

* `frontend/src/india_legacy/pages/HistorifyCharts.tsx`
* `frontend/src/india_legacy/pages/Historify.tsx`
* `frontend/src/india_legacy/pages/StraddleChart.tsx`
* `frontend/src/india_legacy/pages/CustomStraddle.tsx`
* `frontend/src/india_legacy/pages/IVChart.tsx`
* `frontend/src/india_legacy/pages/IVSmile.tsx`
* `frontend/src/india_legacy/pages/OITracker.tsx`
* `frontend/src/india_legacy/pages/OIProfile.tsx`
* `frontend/src/india_legacy/pages/GEXDashboard.tsx`
* `frontend/src/india_legacy/pages/TradingView.tsx`
* `frontend/src/india_legacy/pages/GoCharting.tsx`
* `frontend/src/india_legacy/pages/chartink/*`
* `frontend/src/pages/MaxPain.tsx`
* `frontend/src/pages/VolSurface.tsx`
* `frontend/src/pages/PnLTracker.tsx`
* `frontend/src/pages/HealthMonitor.tsx`
* `frontend/src/india_legacy/components/strategy-builder/PayoffChart.tsx`

## Backend table

Frozen (legacy):

* `market_regions/india/legacy_v1/*` (entirety)
* `services/chart_service.py` (re-export shim)
* `services/historify_service.py`, `services/historify_scheduler_service.py` (re-export shims)
* `database/historify_db.py` (re-export shim)
* `/historify/api/data` blueprint
* `/api/v1/history`, `/api/v1/chart`

New (Phase 1-6):

* `services/charts/*` — bar resampler, intervals service,
  normalized bar shape, Valkey client, WS envelope, bar aggregator,
  tick publisher, ws-fanout, indicator catalog + compute,
  talipp service, safety defaults, pre-trade validator, audit logger.
* `restx_api/v2/chart/*` — full CRUD for layouts, drawings,
  indicators, watchlists, templates, active-layout.
* `restx_api/v2/{indicators_series,strategy_signals,chart_audit}.py`
* `restx_api/v2/streaming.py` — multiplexed SocketIO namespace
  `/charts/streaming` for live tick fan-out.
* `database/chart_workspace_db.py` — 9 additive tables (Phase 1).
* `frontend/src/charts/*` — types, datafeed, engine adapters,
  workspace, display, execution, persistence.
* `broker/alpaca/streaming/alpaca_market_data_stream.py` — concrete
  `BrokerMarketDataStream` impl (Phase 4).

The legacy `chart_preferences` table is preserved untouched.

## API differences

| Concern | Legacy | New |
|---|---|---|
| Historical bars | `/historify/api/data`, `/api/v1/history` | `/api/v2/bars` (uses `services/charts/bar_resampler.py` for non-1m) |
| Quotes | `/api/v1/quotes` | `/api/v2/quotes` |
| Streaming | Per-page WebSocket (broker-specific in `india_legacy/`) | `/charts/streaming` SocketIO namespace |
| Layouts | `chart_preferences` row, key/value | `chart_workspace_layouts.cells_json` (versioned, structured) |
| Drawings | None (legacy pages don't persist) | `chart_drawings` (JSON, engine-agnostic) |
| Indicators | None (legacy pages own their compute) | `chart_indicators` + `/api/v2/indicators/series` |
| Order entry | Legacy pages don't have chart-based order entry | Phase 6 HUD with two-step + idempotency + audit |

## When does a legacy page get retired?

Out of scope for this refactor. The legacy pages are kept frozen
because:

* They are deeply tied to Indian-broker plumbing (Indian options
  chains, NFO/BFO derivatives tape, GEX/IV math). The replacement
  needs region-aware analogues, not a port.
* The new workspace is region-agnostic; replacing any individual
  legacy page is a follow-on workstream that picks one feature at a
  time and rebuilds it on the new engine-adapter foundation.
* Operators of Indian-only deployments still want the legacy pages.

The Phase 7 contract is "the new workspace doesn't break or
modify the legacy pages." That contract is enforced via the
`git diff` check in `tests/contracts/test_legacy_paths_unmodified.py`
+ the smoke E2E in `frontend/e2e/legacy_charts_smoke.spec.ts`.
