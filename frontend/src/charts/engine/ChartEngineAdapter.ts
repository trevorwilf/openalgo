// Phase 2 — Workspace Shell
// Engine-agnostic adapter contract per HANDOFF §5 / Appendix B§6.2.
// Pure interface — Phase 3 ships LightweightAdapter and KLineChartProAdapter
// implementations.
//
// P-02: code outside frontend/src/charts/engine/loader.ts and the
// adapter modules NEVER imports an engine directly. Components mount
// adapters via `loadEngine(engineId)`.
//
// P-03: adapters NEVER call broker APIs directly — all data flows
// through the `frontend/src/charts/datafeed/*` modules.

import type { NormalizedBar } from '../types/bar'
import type { NormalizedTick } from '../types/tick'

export type Theme = 'light' | 'dark'

export interface MountArgs {
  /** Container DOM element the engine attaches to. */
  container: HTMLElement
  /** Initial theme. */
  theme: Theme
  /** Initial size (engines that don't auto-observe still need bounds). */
  width: number
  height: number
}

export interface PaneSpec {
  /** Pane identifier — adapters map this to their native pane API. */
  id: string
  /** Relative pane height in [0, 1]. Sum across panes need not equal 1;
   *  adapters renormalize. */
  height: number
}

export interface IndicatorSpec {
  /** Stable indicator id (matches chart_indicators row). */
  id: string
  /** Catalog key from services/charts/indicator_catalog.py (Phase 5). */
  key: string
  /** Per-indicator parameters from `params_json`. */
  params: Record<string, unknown>
  /** Pane id this indicator renders into. */
  paneId: string
  /** Pre-computed series (from /api/v2/indicators/series). When live,
   *  Phase 4 streams updates via `updateIndicator`. */
  series?: { t: number; values: Record<string, number | null> }[]
}

export interface DrawingSpec {
  /** Stable drawing id (matches chart_drawings row). */
  id: string
  /** Drawing kind ('trendline' | 'horizontal' | 'rectangle' | …). */
  kind: string
  /** Drawing-kind-specific params from `params_json`. */
  params: Record<string, unknown>
}

/** Engine-independent state snapshot used by Phase 5 persistence. */
export interface EngineState {
  bars: NormalizedBar[]
  panes: PaneSpec[]
  indicators: IndicatorSpec[]
  drawings: DrawingSpec[]
  theme: Theme
}

/** Pixel-coordinate accessors used by Phase 6 order entry. */
export interface CoordinateConverter {
  /** Maps a price to a Y pixel within the engine container. */
  getPriceCoordinate(price: number): number | null
  /** Maps a UTC seconds timestamp to an X pixel. */
  getTimeCoordinate(tsSeconds: number): number | null
}

export type TickCallback = (tick: NormalizedTick) => void

export interface ChartEngineAdapter extends CoordinateConverter {
  /** Engine identifier (matches the loader key). */
  readonly engineId: 'lightweight' | 'klinechart_pro' | 'tradingview_advanced'

  /** Mount the engine into the supplied container. Idempotent — calling
   *  twice on the same instance is a no-op after the first call. */
  mount(args: MountArgs): Promise<void>

  /** Tear down the engine, freeing all resources. */
  unmount(): void

  /** Replace the entire bar series — used on initial load and timeframe
   *  switches. */
  setBars(bars: NormalizedBar[]): void

  /** Append a single new bar (no replacement). */
  appendBar(bar: NormalizedBar): void

  /** Update the in-progress bar with current OHLC. */
  updateForming(bar: NormalizedBar): void

  /** Add/replace an indicator. Pre-computed series wins when supplied;
   *  otherwise the adapter consults its native indicator pack. */
  addIndicator(spec: IndicatorSpec): void

  /** Update the trailing values of an existing indicator (used by
   *  talipp incremental updates in Phase 4). */
  updateIndicator(id: string, t: number, values: Record<string, number | null>): void

  /** Remove an indicator. */
  removeIndicator(id: string): void

  /** Add/replace a drawing. */
  addDrawing(spec: DrawingSpec): void

  /** Remove a drawing. */
  removeDrawing(id: string): void

  /** Apply theme. */
  setTheme(theme: Theme): void

  /** Resize handler — called by the host on container resize. */
  resize(width: number, height: number): void

  /** Subscribe to internal events the adapter emits (drawing changed,
   *  pane resize, etc.). Returns an unsubscribe handle. */
  onEvent(handler: (event: AdapterEvent) => void): () => void

  /** Engine-independent state snapshot for persistence. */
  serializeState(): EngineState

  /** Restore from a snapshot produced by `serializeState`. */
  restoreState(state: EngineState): void
}

export type AdapterEvent =
  | { kind: 'mounted' }
  | { kind: 'unmounted' }
  | { kind: 'theme_changed'; theme: Theme }
  | { kind: 'drawing_changed'; id: string; spec: DrawingSpec }
  | { kind: 'pane_resized'; id: string; height: number }
  | { kind: 'error'; message: string }
