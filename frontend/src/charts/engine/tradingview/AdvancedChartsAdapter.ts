// Phase 3 — TradingView Advanced Charts adapter STUB.
//
// D-01 / P-11: Advanced Charts is FAC-licensed and never shipped in
// the OSS repo. The runtime probe at `loader.tradingViewSdkAvailable`
// returns false by default; the loader logs a warning and falls back
// to the Lightweight adapter.
//
// This stub exists only so the loader's `loadAdvanced` importer has
// something to dynamic-import in environments where the SDK has been
// dropped at `frontend/private/tradingview/charting_library/`. When
// the SDK is absent, this file is never loaded.
//
// **No static `import` of any path under `frontend/private/`** — the
// SDK module is loaded lazily via `import('../../../../private/...')`
// from `loader.ts`'s default importer (which we override at runtime
// via `setAdapterImporters` when the operator drops their SDK in).
//
// Phase 3 does NOT mount Advanced Charts. The adapter throws on
// every method, which surfaces a clear error if anyone tries to
// instantiate it without a real SDK present.

import type {
  AdapterEvent,
  ChartEngineAdapter,
  DrawingSpec,
  EngineState,
  IndicatorSpec,
  MountArgs,
  Theme,
} from '../ChartEngineAdapter'

const NOT_AVAILABLE =
  'TradingView Advanced Charts adapter is a Phase 3 stub — the FAC ' +
  'SDK files at frontend/private/tradingview/charting_library/ are ' +
  'absent (the OSS default). Drop your SDK files there + register a ' +
  'real adapter via setAdapterImporters({ loadAdvanced: ... }) to ' +
  'enable.'

export class AdvancedChartsStubAdapter implements ChartEngineAdapter {
  readonly engineId = 'tradingview_advanced' as const

  async mount(_args: MountArgs): Promise<void> {
    throw new Error(NOT_AVAILABLE)
  }

  unmount(): void {
    /* nothing to clean up — never mounted */
  }

  setBars(_bars: unknown): void {
    throw new Error(NOT_AVAILABLE)
  }

  appendBar(_bar: unknown): void {
    throw new Error(NOT_AVAILABLE)
  }

  updateForming(_bar: unknown): void {
    throw new Error(NOT_AVAILABLE)
  }

  addIndicator(_spec: IndicatorSpec): void {
    throw new Error(NOT_AVAILABLE)
  }

  updateIndicator(_id: string, _t: number, _values: Record<string, number | null>): void {
    throw new Error(NOT_AVAILABLE)
  }

  removeIndicator(_id: string): void {
    throw new Error(NOT_AVAILABLE)
  }

  addDrawing(_spec: DrawingSpec): void {
    throw new Error(NOT_AVAILABLE)
  }

  removeDrawing(_id: string): void {
    throw new Error(NOT_AVAILABLE)
  }

  setTheme(_theme: Theme): void {
    throw new Error(NOT_AVAILABLE)
  }

  resize(_width: number, _height: number): void {
    /* no chart mounted — silent no-op so layout-driven resize calls
     * don't crash before mount() is even attempted */
  }

  onEvent(_handler: (event: AdapterEvent) => void): () => void {
    return () => undefined
  }

  serializeState(): EngineState {
    return { bars: [], panes: [], indicators: [], drawings: [], theme: 'dark' }
  }

  restoreState(_state: EngineState): void {
    throw new Error(NOT_AVAILABLE)
  }

  getPriceCoordinate(_price: number): number | null {
    return null
  }

  getTimeCoordinate(_tsSeconds: number): number | null {
    return null
  }
}

/** Loader entrypoint — Phase 2's loader expects this factory. */
export function createAdapter(): ChartEngineAdapter {
  return new AdvancedChartsStubAdapter()
}
