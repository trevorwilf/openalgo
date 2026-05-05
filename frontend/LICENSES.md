# Premier Charting System — third-party licenses

The chart workspace introduced in Phase 1+ depends on three engine
options. This file lists each engine's license and our compliance
obligations for users who clone or fork OpenAlgo.

## Lightweight Charts (default engine)

* Package: `lightweight-charts@^5.1.0`
* License: Apache-2.0
* Source: https://github.com/tradingview/lightweight-charts

### Attribution requirement (P-12)

TradingView's Lightweight Charts library is free for commercial use
under Apache-2.0 with one binding obligation: the chart must display
an attribution link to tradingview.com via the `attributionLogo`
option, and the build artifacts must include a `NOTICE` entry naming
TradingView Inc.

Our `LightweightAdapter` configures `attributionLogo: true` on every
chart instance (Phase 3, `frontend/src/charts/engine/lightweight/
LightweightAdapter.ts`). Removing or hiding the link is a license
violation.

## KLineChart Pro

* Packages: `@klinecharts/pro@^0.1.1`, `klinecharts@^9.8.12`
* License: Apache-2.0
* Source: https://github.com/klinecharts/pro

KLineChart Pro is a higher-level frame on top of `klinecharts`. Both
packages are Apache-2.0; no extra attribution clause beyond the
standard Apache-2.0 NOTICE inheritance.

## TradingView Advanced Charts (optional)

* SDK distribution: `frontend/private/tradingview/charting_library/`
  (gitignored — not shipped in the OSS repo)
* License: TradingView FAC (Free Advanced Charts) — per-deployment
  click-through agreement.
* Source: https://www.tradingview.com/charting-library-docs/

We do **not** ship the FAC SDK. The loader at
`frontend/src/charts/engine/loader.ts` follows §0.3:

* If the SDK files are present locally, it dynamic-imports the
  `AdvancedChartsAdapter` and uses Advanced Charts.
* If absent (the default), it logs a warning and falls back to
  Lightweight Charts — every public chart workspace works without
  any TradingView SDK file present.

Operators who have a valid FAC license may drop the SDK at the
gitignored path on their own deployment.

## Indicator math libraries (Phase 5)

These wire up in Phase 5 — listed here so the legal review covers the
whole charting stack at once.

* `talipp` — MIT (live incremental indicators).
* `TA-Lib` — BSD-2-Clause (batch path; the C library + Python wrapper).
* `pandas-ta` — MIT (pinned to the last stable PyPI release;
  `MerlinR/Pandas-ta-fork` is documented as a fallback if the
  upstream package goes unmaintained).
* `vectorbt` — Apache-2.0 + Commons Clause. Acceptable for personal
  /internal use only. The Commons Clause restricts commercial
  redistribution; flagged for re-evaluation if OpenAlgo's distribution
  model ever changes.

## Compliance summary

| Library | License | Action |
|---|---|---|
| Lightweight Charts | Apache-2.0 | `attributionLogo` on every chart + `NOTICE` entry |
| KLineChart Pro | Apache-2.0 | Standard Apache `NOTICE` inheritance |
| Advanced Charts (optional) | FAC (per-deployment) | NEVER committed; gitignored at `frontend/private/tradingview/` |
| talipp | MIT | None |
| TA-Lib | BSD-2-Clause | None |
| pandas-ta | MIT | None |
| vectorbt | Apache-2.0 + Commons Clause | Re-eval if commercial redistribution model changes |
