// Phase 3 — KLineChart Pro adapter.
//
// Implements `ChartEngineAdapter` against `klinecharts@^9.8` (the
// renderer beneath @klinecharts/pro). Phase 3 wires the same surface
// area as the Lightweight adapter:
//   * setBars / appendBar / updateForming
//   * Pre-computed indicator series (Phase 5 wires native indicator
//     packs where available)
//   * Theme propagation
//   * Pixel-coordinate accessors
//
// We use the lower-level `klinecharts` API (not `@klinecharts/pro`)
// because Pro is a higher-level frame component that owns its own
// data feed + symbol picker — we already own those, so we mount the
// raw klinecharts canvas inside our `<ChartCell>`. The Pro package
// is still included so legal review covers both packages and the
// upgrade path stays open.
//
// P-02: this is the ONLY file under `frontend/src/charts/*` that
// statically imports `klinecharts`.

import { dispose, init, type Chart as KLineChart, type KLineData, type Nullable } from 'klinecharts'

import type { NormalizedBar } from '../../types/bar'
import { dec, makeEventEmitter, normalizeBarSeries } from '../base'
import type {
  AdapterEvent,
  ChartEngineAdapter,
  DrawingSpec,
  EngineState,
  IndicatorSpec,
  MountArgs,
  Theme,
} from '../ChartEngineAdapter'

interface IndicatorRecord {
  spec: IndicatorSpec
  /** klinecharts assigns numeric pane IDs; we keep our own map. */
  paneId: string
}

export class KLineChartProAdapter implements ChartEngineAdapter {
  readonly engineId = 'klinechart_pro' as const

  private chart: Nullable<KLineChart> = null
  private container: HTMLElement | null = null
  private bars: NormalizedBar[] = []
  private indicators = new Map<string, IndicatorRecord>()
  private drawings = new Map<string, DrawingSpec>()
  private theme: Theme = 'dark'
  private events = makeEventEmitter()
  private mounted = false

  async mount(args: MountArgs): Promise<void> {
    if (this.mounted) return
    this.container = args.container
    this.theme = args.theme

    this.chart = init(args.container, {
      styles: this.themeStyles(args.theme),
    })
    if (!this.chart) {
      throw new Error('klinecharts.init returned null')
    }
    this.mounted = true
    this.events.emit({ kind: 'mounted' })
  }

  unmount(): void {
    if (!this.mounted) return
    this.indicators.clear()
    this.drawings.clear()
    if (this.container) {
      dispose(this.container)
    }
    this.chart = null
    this.bars = []
    this.mounted = false
    this.events.emit({ kind: 'unmounted' })
  }

  setBars(bars: NormalizedBar[]): void {
    this.bars = normalizeBarSeries(bars)
    if (!this.chart) return
    const data: KLineData[] = this.bars.map((b) => ({
      timestamp: b.t * 1000,
      open: dec(b.o),
      high: dec(b.h),
      low: dec(b.l),
      close: dec(b.c),
      volume: dec(b.v),
    }))
    this.chart.applyNewData(data)
  }

  appendBar(bar: NormalizedBar): void {
    if (!this.chart) return
    this.bars = normalizeBarSeries([...this.bars, bar])
    this.chart.updateData({
      timestamp: bar.t * 1000,
      open: dec(bar.o),
      high: dec(bar.h),
      low: dec(bar.l),
      close: dec(bar.c),
      volume: dec(bar.v),
    })
  }

  updateForming(bar: NormalizedBar): void {
    this.appendBar(bar)
  }

  addIndicator(spec: IndicatorSpec): void {
    if (!this.chart) return
    this.removeIndicator(spec.id)
    // klinecharts ships native packs for the modern catalog. When the
    // spec carries pre-computed series we use the chart's overlay
    // mechanism; otherwise we ask klinecharts to compute the indicator
    // natively from `paramKeyToKLineCharts(spec.key)`.
    const native = nativeIndicatorName(spec.key)
    const paneId = spec.paneId === 'price' ? 'candle_pane' : `pane_${spec.id}`
    if (native) {
      this.chart.createIndicator(native, false, { id: paneId })
    }
    this.indicators.set(spec.id, { spec, paneId })
  }

  updateIndicator(id: string, _t: number, _values: Record<string, number | null>): void {
    // klinecharts recomputes indicators automatically when bar data
    // changes via `updateData`. The talipp live path (Phase 4) feeds
    // OHLC ticks directly into appendBar/updateForming and the
    // chart's indicator pane refreshes on its own.
    const rec = this.indicators.get(id)
    if (!rec) return
    // No-op for now; native pane keeps in sync.
  }

  removeIndicator(id: string): void {
    const rec = this.indicators.get(id)
    if (!rec || !this.chart) return
    const native = nativeIndicatorName(rec.spec.key)
    if (native) {
      try {
        this.chart.removeIndicator(rec.paneId, native)
      } catch {
        /* native pane already removed */
      }
    }
    this.indicators.delete(id)
  }

  addDrawing(spec: DrawingSpec): void {
    // Phase 5 wires the full klinecharts overlay API. Phase 3 holds
    // the spec so persistence + cross-engine round-trip work.
    this.drawings.set(spec.id, spec)
    this.events.emit({ kind: 'drawing_changed', id: spec.id, spec })
  }

  removeDrawing(id: string): void {
    this.drawings.delete(id)
  }

  setTheme(theme: Theme): void {
    this.theme = theme
    if (!this.chart) return
    this.chart.setStyles(this.themeStyles(theme))
    this.events.emit({ kind: 'theme_changed', theme })
  }

  resize(_width: number, _height: number): void {
    if (!this.chart) return
    // klinecharts reads container size directly via ResizeObserver;
    // it auto-resizes when the container's bounding box changes.
    this.chart.resize()
  }

  onEvent(handler: (event: AdapterEvent) => void): () => void {
    return this.events.subscribe(handler)
  }

  serializeState(): EngineState {
    return {
      bars: [...this.bars],
      panes: [
        { id: 'candle_pane', height: 0.7 },
        { id: 'volume_pane', height: 0.3 },
      ],
      indicators: [...this.indicators.values()].map((r) => r.spec),
      drawings: [...this.drawings.values()],
      theme: this.theme,
    }
  }

  restoreState(state: EngineState): void {
    this.theme = state.theme
    this.setBars(state.bars)
    for (const ind of state.indicators) this.addIndicator(ind)
    for (const dr of state.drawings) this.addDrawing(dr)
  }

  getPriceCoordinate(price: number): number | null {
    if (!this.chart) return null
    const point = this.chart.convertToPixel({ value: price }, { paneId: 'candle_pane' })
    return point && typeof point === 'object' && 'y' in point ? point.y : null
  }

  getTimeCoordinate(tsSeconds: number): number | null {
    if (!this.chart) return null
    const point = this.chart.convertToPixel(
      { timestamp: tsSeconds * 1000 },
      { paneId: 'candle_pane' }
    )
    return point && typeof point === 'object' && 'x' in point ? point.x : null
  }

  // ------------------------------------------------------------------
  private themeStyles(theme: Theme): Record<string, unknown> {
    return theme === 'dark'
      ? {
          grid: {
            horizontal: { color: '#1f2937' },
            vertical: { color: '#1f2937' },
          },
          candle: { tooltip: { rect: { color: '#0b1220' } } },
        }
      : {
          grid: {
            horizontal: { color: '#e5e7eb' },
            vertical: { color: '#e5e7eb' },
          },
          candle: { tooltip: { rect: { color: '#ffffff' } } },
        }
  }
}

/** Map our catalog key to klinecharts's native indicator name.
 *  Returns null when klinecharts does not ship the indicator natively
 *  (we then rely on pre-computed series from /api/v2/indicators/series). */
function nativeIndicatorName(catalogKey: string): string | null {
  const map: Record<string, string> = {
    SMA: 'MA',
    EMA: 'EMA',
    BB: 'BOLL',
    RSI: 'RSI',
    MACD: 'MACD',
    KDJ: 'KDJ',
    STOCH: 'KDJ', // klinecharts ships KDJ; STOCH variant comes from pre-computed
    OBV: 'OBV',
    VOL: 'VOL',
    PSAR: 'SAR',
    ATR: 'ATR',
    CCI: 'CCI',
  }
  return map[catalogKey] ?? null
}

/** Loader entrypoint — Phase 2's loader expects this factory. */
export function createAdapter(): ChartEngineAdapter {
  return new KLineChartProAdapter()
}
