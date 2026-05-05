// Phase 3 — Lightweight Charts adapter.
//
// Implements `ChartEngineAdapter` against `lightweight-charts@^5.1.0`.
// Phase 3 ships:
//   * setBars / appendBar / updateForming
//   * Pre-computed indicator series via setBars-style line series
//   * Volume in a v5 pane (NOT priceScaleId: '' — F-007)
//   * Theme propagation
//   * `attributionLogo: true` per P-12
//   * Pixel-coordinate accessors for Phase 6 order-entry HUD
//
// Phase 5 + Phase 6 layer on per-engine drawings + per-pane indicator
// management.
//
// P-02: this is the ONLY file under `frontend/src/charts/*` that
// statically imports `lightweight-charts`.

import {
  type Background,
  CandlestickSeries,
  type CandlestickSeriesPartialOptions,
  ColorType,
  createChart,
  HistogramSeries,
  type IChartApi,
  type ISeriesApi,
  LineSeries,
  type Time,
} from 'lightweight-charts'

import type { NormalizedBar } from '../../types/bar'
import { dec, makeEventEmitter, normalizeBarSeries, toLineSeriesData } from '../base'
import type {
  AdapterEvent,
  ChartEngineAdapter,
  DrawingSpec,
  EngineState,
  IndicatorSpec,
  MountArgs,
  Theme,
} from '../ChartEngineAdapter'

const PANE_PRICE = 0
const PANE_VOLUME = 1

interface IndicatorRecord {
  spec: IndicatorSpec
  series: ISeriesApi<'Line'>[]
}

export class LightweightAdapter implements ChartEngineAdapter {
  readonly engineId = 'lightweight' as const

  private chart: IChartApi | null = null
  private candleSeries: ISeriesApi<'Candlestick'> | null = null
  private volumeSeries: ISeriesApi<'Histogram'> | null = null
  private indicators = new Map<string, IndicatorRecord>()
  private drawings = new Map<string, DrawingSpec>()
  private bars: NormalizedBar[] = []
  private theme: Theme = 'dark'
  private container: HTMLElement | null = null
  private events = makeEventEmitter()
  private mounted = false

  async mount(args: MountArgs): Promise<void> {
    if (this.mounted) return
    this.container = args.container
    this.theme = args.theme

    this.chart = createChart(args.container, {
      width: args.width,
      height: args.height,
      ...this.themeOptions(args.theme),
      // Lightweight Charts v5 attribution requirement (P-12).
      // Renders a small "TradingView" link in the corner that the user
      // can click through to tradingview.com — the license obligation
      // for Apache-2.0 use of the library.
      attributionLogo: true,
      timeScale: {
        timeVisible: true,
        secondsVisible: true,
        borderVisible: false,
      },
      rightPriceScale: { borderVisible: false },
    })

    this.candleSeries = this.chart.addSeries(CandlestickSeries, this.candleOptions(args.theme))

    // Volume in its own v5 pane (NOT the legacy `priceScaleId: ''`
    // pattern — F-007 forbids it). Lightweight v5 returns one
    // pane per series via `.moveToPane`.
    this.volumeSeries = this.chart.addSeries(
      HistogramSeries,
      {
        priceFormat: { type: 'volume' },
        priceScaleId: '',
      },
      PANE_VOLUME
    )

    this.mounted = true
    this.events.emit({ kind: 'mounted' })
  }

  unmount(): void {
    if (!this.mounted) return
    this.indicators.clear()
    this.drawings.clear()
    if (this.chart) {
      this.chart.remove()
    }
    this.chart = null
    this.candleSeries = null
    this.volumeSeries = null
    this.bars = []
    this.mounted = false
    this.events.emit({ kind: 'unmounted' })
  }

  setBars(bars: NormalizedBar[]): void {
    this.bars = normalizeBarSeries(bars)
    if (!this.candleSeries || !this.volumeSeries) return
    this.candleSeries.setData(
      this.bars.map((b) => ({
        time: b.t as unknown as Time,
        open: dec(b.o),
        high: dec(b.h),
        low: dec(b.l),
        close: dec(b.c),
      }))
    )
    this.volumeSeries.setData(
      this.bars.map((b) => ({
        time: b.t as unknown as Time,
        value: dec(b.v),
        color: dec(b.c) >= dec(b.o) ? '#22c55e' : '#ef4444',
      }))
    )
  }

  appendBar(bar: NormalizedBar): void {
    if (!this.candleSeries || !this.volumeSeries) return
    this.bars = normalizeBarSeries([...this.bars, bar])
    this.candleSeries.update({
      time: bar.t as unknown as Time,
      open: dec(bar.o),
      high: dec(bar.h),
      low: dec(bar.l),
      close: dec(bar.c),
    })
    this.volumeSeries.update({
      time: bar.t as unknown as Time,
      value: dec(bar.v),
      color: dec(bar.c) >= dec(bar.o) ? '#22c55e' : '#ef4444',
    })
  }

  updateForming(bar: NormalizedBar): void {
    // For Lightweight Charts, `update()` on the same `time` replaces
    // the bar — same path as `appendBar` once the bucket exists.
    this.appendBar(bar)
  }

  addIndicator(spec: IndicatorSpec): void {
    if (!this.chart) return
    // Always replace — addIndicator with an existing id is treated as
    // an update (consistent with KLineChart Pro's behavior).
    this.removeIndicator(spec.id)
    if (!spec.series || spec.series.length === 0) {
      // Without pre-computed series we can't render — Phase 5 wires
      // /api/v2/indicators/series; Phase 4 streams updates via talipp.
      this.indicators.set(spec.id, { spec, series: [] })
      return
    }
    const seriesKeys = collectSeriesKeys(spec.series)
    const lines: ISeriesApi<'Line'>[] = []
    for (const key of seriesKeys) {
      const data = toLineSeriesData(spec.series, key).map((d) => ({
        time: d.time as unknown as Time,
        value: d.value,
      }))
      const line = this.chart.addSeries(
        LineSeries,
        {
          color: indicatorColor(spec.key, key),
          lineWidth: 1,
          priceScaleId: '',
        },
        spec.paneId === 'price' ? PANE_PRICE : PANE_VOLUME + 1
      )
      line.setData(data)
      lines.push(line)
    }
    this.indicators.set(spec.id, { spec, series: lines })
  }

  updateIndicator(id: string, t: number, values: Record<string, number | null>): void {
    const rec = this.indicators.get(id)
    if (!rec) return
    const seriesKeys = rec.spec.series ? collectSeriesKeys(rec.spec.series) : Object.keys(values)
    rec.series.forEach((line, i) => {
      const key = seriesKeys[i]
      const v = values[key]
      if (v == null || !Number.isFinite(v)) return
      line.update({ time: t as unknown as Time, value: v })
    })
  }

  removeIndicator(id: string): void {
    const rec = this.indicators.get(id)
    if (!rec || !this.chart) return
    for (const s of rec.series) {
      try {
        this.chart.removeSeries(s)
      } catch {
        /* series already gone — ignore */
      }
    }
    this.indicators.delete(id)
  }

  addDrawing(spec: DrawingSpec): void {
    // Phase 5 lands the full drawing toolbar via Series Primitives.
    // Phase 3 records the spec only; the visual implementation is
    // intentionally deferred so the engine adapter contract surface is
    // testable today.
    this.drawings.set(spec.id, spec)
    this.events.emit({ kind: 'drawing_changed', id: spec.id, spec })
  }

  removeDrawing(id: string): void {
    this.drawings.delete(id)
  }

  setTheme(theme: Theme): void {
    this.theme = theme
    if (!this.chart) return
    this.chart.applyOptions(this.themeOptions(theme))
    if (this.candleSeries) {
      this.candleSeries.applyOptions(this.candleOptions(theme))
    }
    this.events.emit({ kind: 'theme_changed', theme })
  }

  resize(width: number, height: number): void {
    if (!this.chart) return
    this.chart.resize(width, height)
  }

  onEvent(handler: (event: AdapterEvent) => void): () => void {
    return this.events.subscribe(handler)
  }

  serializeState(): EngineState {
    return {
      bars: [...this.bars],
      panes: [
        { id: 'price', height: 0.7 },
        { id: 'volume', height: 0.3 },
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
    if (!this.candleSeries) return null
    const c = this.candleSeries.priceToCoordinate(price)
    return c == null ? null : c
  }

  getTimeCoordinate(tsSeconds: number): number | null {
    if (!this.chart) return null
    const c = this.chart.timeScale().timeToCoordinate(tsSeconds as unknown as Time)
    return c == null ? null : c
  }

  // ------------------------------------------------------------------
  private themeOptions(theme: Theme) {
    return theme === 'dark'
      ? {
          layout: {
            background: { type: ColorType.Solid, color: '#0b1220' } as Background,
            textColor: '#cbd5e1',
          },
          grid: {
            vertLines: { color: '#1f2937' },
            horzLines: { color: '#1f2937' },
          },
        }
      : {
          layout: {
            background: { type: ColorType.Solid, color: '#ffffff' } as Background,
            textColor: '#0f172a',
          },
          grid: {
            vertLines: { color: '#e5e7eb' },
            horzLines: { color: '#e5e7eb' },
          },
        }
  }

  private candleOptions(theme: Theme): CandlestickSeriesPartialOptions {
    return theme === 'dark'
      ? {
          upColor: '#22c55e',
          downColor: '#ef4444',
          wickUpColor: '#22c55e',
          wickDownColor: '#ef4444',
          borderVisible: false,
        }
      : {
          upColor: '#16a34a',
          downColor: '#dc2626',
          wickUpColor: '#16a34a',
          wickDownColor: '#dc2626',
          borderVisible: false,
        }
  }
}

/** Stable order of series keys across an indicator's payload. */
function collectSeriesKeys(rows: { values: Record<string, number | null> }[]): string[] {
  const seen = new Set<string>()
  for (const row of rows) {
    for (const k of Object.keys(row.values)) seen.add(k)
  }
  return [...seen]
}

/** Deterministic color choice per indicator/key pair. */
function indicatorColor(indicatorKey: string, seriesKey: string): string {
  const palette = ['#60a5fa', '#a78bfa', '#f472b6', '#facc15', '#34d399', '#fb923c']
  let h = 0
  const s = `${indicatorKey}:${seriesKey}`
  for (let i = 0; i < s.length; i += 1) h = (h * 31 + s.charCodeAt(i)) >>> 0
  return palette[h % palette.length]
}

/** Loader entrypoint — Phase 2's loader expects each adapter module
 *  to expose a `createAdapter()` factory. */
export function createAdapter(): ChartEngineAdapter {
  return new LightweightAdapter()
}
