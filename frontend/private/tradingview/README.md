# TradingView Advanced Charts SDK (private)

This directory is intentionally empty in the OSS checkout.

## Why empty

The TradingView Advanced Charts JavaScript bundle is licensed under the
[FAC (Free Advanced Charts)](https://www.tradingview.com/charting-library-docs/latest/getting_started/Access-the-Library/)
program. Distribution requires a per-deployment license — we do **not**
ship the SDK files in the public repository.

## How the runtime resolves this

The chart engine loader at `frontend/src/charts/engine/loader.ts`
follows the §0.3 decision tree:

1. If `engine === 'tradingview_advanced'` and the SDK files at
   `frontend/private/tradingview/charting_library/` are present, the
   loader dynamic-imports `AdvancedChartsAdapter` and mounts it.
2. If the files are absent (the OSS default), the loader emits a
   `console.warn("Advanced Charts files missing; falling back to
   Lightweight Charts")` and resolves to the Lightweight adapter.

The static bundle compiles cleanly without any SDK file present
because the loader is the only place that imports an adapter, and it
does so via `import()` (dynamic). No file under
`frontend/src/charts/*` ever statically references this directory
(P-11 hard rule).

## Dropping in your SDK files

If you have a valid FAC license and want to enable Advanced Charts
locally, place the SDK at:

```
frontend/private/tradingview/charting_library/
```

That directory is git-ignored (`frontend/private/` is in
`.gitignore`). Do not commit the SDK or any file under
`frontend/private/`.

## CI guard

A Phase 8 CI job (`verify-tradingview-private-empty`) fails the build
if any file matching the SDK signature ever lands in the repo. The
intent is forensic — even an accidental commit of the SDK is caught
before it reaches `main`.
