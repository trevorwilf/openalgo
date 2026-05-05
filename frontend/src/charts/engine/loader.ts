// Phase 2 — Workspace Shell
// Engine loader / fallback per HANDOFF §0.3.
//
// This file is the ONLY place that maps an engine string to an adapter
// module. Components import the loader, never an adapter directly
// (P-02). The adapter modules themselves are NEVER statically imported
// here — the loader uses dynamic `import()` so the static bundle stays
// clean even when `frontend/private/tradingview/` is empty.
//
// Runtime decision tree:
//
//   1. engine === 'tradingview_advanced':
//      - Is `frontend/private/tradingview/charting_library/` present
//        at runtime? (probed via `tradingViewSdkAvailable`)
//        - YES: dynamic-import AdvancedChartsAdapter, mount.
//        - NO:  console.warn + fall through to 'lightweight'.
//   2. engine === 'klinechart_pro': dynamic-import KLineChartProAdapter.
//   3. engine === 'lightweight' (default): dynamic-import LightweightAdapter.
//
// Phase 3 ships Lightweight + KLineChart Pro live. AdvancedChartsAdapter
// is stubbed only — the SDK files at `frontend/private/tradingview/`
// are gitignored and absent in the OSS checkout, so the runtime probe
// returns `false` and the loader falls back to Lightweight.

import type { EngineId } from '../state/workspaceStore'
import type { ChartEngineAdapter } from './ChartEngineAdapter'

export interface LoadEngineResult {
  /** The adapter the loader actually mounted. May differ from the
   *  caller's request when an engine is unavailable and a fallback
   *  was used. */
  adapter: ChartEngineAdapter
  /** What the caller asked for. */
  requested: EngineId
  /** What was loaded. When `requested !== resolved`, a fallback fired
   *  and the caller may want to surface a notice. */
  resolved: EngineId
  /** Set when a fallback fired. */
  fallback: { from: EngineId; reason: string } | null
}

/**
 * Probe whether the TradingView Advanced Charts SDK is present.
 *
 * Default implementation returns `false` (the SDK files at
 * `frontend/private/tradingview/charting_library/` are gitignored and
 * absent in the OSS checkout). Tests inject a custom probe via
 * `setTradingViewSdkAvailability` to exercise the YES branch without
 * shipping a real SDK.
 */
let _tvProbe: () => boolean = () => false

/** Test-only seam for the §0.3 decision-tree YES-branch test. */
export function setTradingViewSdkAvailability(probe: () => boolean): void {
  _tvProbe = probe
}

export function tradingViewSdkAvailable(): boolean {
  try {
    return _tvProbe()
  } catch {
    return false
  }
}

/** Test-only seam — adapter dynamic-imports go through these so test
 *  code can swap in a fake without bundling the engine. Production
 *  code never assigns to these. */
export interface AdapterImporters {
  loadLightweight(): Promise<{ createAdapter: () => ChartEngineAdapter }>
  loadKlineChartPro(): Promise<{ createAdapter: () => ChartEngineAdapter }>
  loadAdvanced(): Promise<{ createAdapter: () => ChartEngineAdapter }>
}

let _importers: AdapterImporters = {
  // Phase 3 wires real implementations. Phase 2 ships only the
  // contract surface — these throw if invoked, signalling "Phase 3
  // hasn't shipped yet" rather than silently producing a stub.
  loadLightweight: () =>
    Promise.reject(new Error('Lightweight adapter not yet implemented (Phase 3 ships it)')),
  loadKlineChartPro: () =>
    Promise.reject(new Error('KLineChartPro adapter not yet implemented (Phase 3 ships it)')),
  loadAdvanced: () =>
    Promise.reject(new Error('Advanced Charts adapter is a Phase 3 stub — SDK absent')),
}

/** Test-only seam. Phase 3 will assign the real importers. */
export function setAdapterImporters(importers: Partial<AdapterImporters>): void {
  _importers = { ..._importers, ...importers }
}

/** Reset the importers to their Phase 2 defaults. */
export function resetAdapterImportersForTests(): void {
  _importers = {
    loadLightweight: () =>
      Promise.reject(new Error('Lightweight adapter not yet implemented (Phase 3 ships it)')),
    loadKlineChartPro: () =>
      Promise.reject(new Error('KLineChartPro adapter not yet implemented (Phase 3 ships it)')),
    loadAdvanced: () =>
      Promise.reject(new Error('Advanced Charts adapter is a Phase 3 stub — SDK absent')),
  }
  _tvProbe = () => false
}

/**
 * Resolve + dynamic-import the adapter for `engineId`.
 *
 * Always returns a usable adapter via fallback to Lightweight when
 * the requested engine is unavailable. Throws only if the fallback
 * itself fails to load.
 */
export async function loadEngine(engineId: EngineId): Promise<LoadEngineResult> {
  if (engineId === 'tradingview_advanced') {
    if (tradingViewSdkAvailable()) {
      const mod = await _importers.loadAdvanced()
      return {
        adapter: mod.createAdapter(),
        requested: engineId,
        resolved: 'tradingview_advanced',
        fallback: null,
      }
    }
    // Documented fallback path per §0.3.
    // eslint-disable-next-line no-console
    console.warn('Advanced Charts files missing; falling back to Lightweight Charts')
    const mod = await _importers.loadLightweight()
    return {
      adapter: mod.createAdapter(),
      requested: engineId,
      resolved: 'lightweight',
      fallback: {
        from: 'tradingview_advanced',
        reason: 'sdk_absent',
      },
    }
  }
  if (engineId === 'klinechart_pro') {
    const mod = await _importers.loadKlineChartPro()
    return {
      adapter: mod.createAdapter(),
      requested: engineId,
      resolved: 'klinechart_pro',
      fallback: null,
    }
  }
  // Default: lightweight.
  const mod = await _importers.loadLightweight()
  return {
    adapter: mod.createAdapter(),
    requested: engineId,
    resolved: 'lightweight',
    fallback: null,
  }
}
