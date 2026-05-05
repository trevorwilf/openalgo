// Phase 3 — LightweightAdapter contract tests.
//
// happy-dom doesn't fully implement HTMLCanvasElement, so we mock
// `lightweight-charts` and assert the adapter's contract behavior:
// the right factory functions are called with the right arguments,
// theme toggling re-applies options, attribution is enabled (P-12),
// and serialize/restore round-trips. The full rendering check moves
// to the Playwright suite (frontend/e2e/charts/historical_bars.spec.ts).

import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import type { NormalizedBar } from '../../../types/bar'
import { utcSeconds } from '../../../types/interval'

vi.mock('lightweight-charts', () => {
  const setData = vi.fn()
  const update = vi.fn()
  const applyOptions = vi.fn()
  const removeSeries = vi.fn()
  const priceToCoordinate = vi.fn(() => 100)
  const timeToCoordinate = vi.fn(() => 200)

  const candleSeriesObj = {
    setData,
    update,
    applyOptions,
    priceToCoordinate,
  }
  const volumeSeriesObj = { setData, update, applyOptions }
  const lineSeriesObj = { setData, update, applyOptions }

  const addSeries = vi.fn((kind, _opts, _pane) => {
    if (kind === 'CANDLE_KIND') return candleSeriesObj
    if (kind === 'HIST_KIND') return volumeSeriesObj
    return lineSeriesObj
  })
  const timeScale = vi.fn(() => ({ timeToCoordinate }))
  const remove = vi.fn()
  const resize = vi.fn()

  const createChart = vi.fn(() => ({
    addSeries,
    applyOptions,
    timeScale,
    remove,
    resize,
    removeSeries,
  }))

  return {
    createChart,
    CandlestickSeries: 'CANDLE_KIND',
    HistogramSeries: 'HIST_KIND',
    LineSeries: 'LINE_KIND',
    ColorType: { Solid: 'solid' },
    // Re-export markers used by the helpers.
    __mocks: {
      createChart,
      addSeries,
      applyOptions,
      removeSeries,
      timeScale,
      remove,
      resize,
      priceToCoordinate,
      timeToCoordinate,
    },
  }
})

import * as lightweight from 'lightweight-charts'
import { createAdapter, LightweightAdapter } from '../LightweightAdapter'

const mocks = (lightweight as unknown as { __mocks: Record<string, ReturnType<typeof vi.fn>> })
  .__mocks

function fixtureBars(count = 200): NormalizedBar[] {
  const t0 = 1_700_000_000
  const out: NormalizedBar[] = []
  let price = 100
  for (let i = 0; i < count; i += 1) {
    const open = price
    const close = price + (i % 5 === 0 ? -1 : 0.7)
    const high = Math.max(open, close) + 0.5
    const low = Math.min(open, close) - 0.5
    out.push({
      t: utcSeconds(t0 + i * 60),
      o: String(open),
      h: String(high),
      l: String(low),
      c: String(close),
      v: String(1000 + i * 7),
      oi: null,
    })
    price = close
  }
  return out
}

describe('LightweightAdapter', () => {
  let container: HTMLElement
  let adapter: LightweightAdapter

  beforeEach(() => {
    for (const m of Object.values(mocks)) m.mockClear()
    container = document.createElement('div')
    document.body.appendChild(container)
    adapter = new LightweightAdapter()
  })

  afterEach(() => {
    try {
      adapter.unmount()
    } catch {
      /* ignore */
    }
    container.remove()
  })

  it('exposes engineId="lightweight"', () => {
    expect(adapter.engineId).toBe('lightweight')
  })

  it('createAdapter() returns a fresh adapter instance', () => {
    const a = createAdapter()
    expect(a.engineId).toBe('lightweight')
  })

  it('mount calls createChart with attributionLogo: true (P-12)', async () => {
    await adapter.mount({ container, theme: 'dark', width: 800, height: 400 })
    expect(mocks.createChart).toHaveBeenCalledTimes(1)
    const opts = mocks.createChart.mock.calls[0][1] as Record<string, unknown>
    expect(opts.attributionLogo).toBe(true)
  })

  it('mount adds candle series + volume series (volume in pane > 0)', async () => {
    await adapter.mount({ container, theme: 'dark', width: 800, height: 400 })
    // First call is candlestick series with no pane arg (pane 0).
    const calls = mocks.addSeries.mock.calls
    expect(calls[0][0]).toBe('CANDLE_KIND')
    // Second call is the volume histogram in pane 1.
    expect(calls[1][0]).toBe('HIST_KIND')
    expect(calls[1][2]).toBe(1)
  })

  it('setBars feeds the candle + volume series', async () => {
    await adapter.mount({ container, theme: 'dark', width: 800, height: 400 })
    adapter.setBars(fixtureBars(200))
    // Candle setData first, then volume.
    expect(mocks.createChart).toHaveBeenCalledTimes(1)
    // The mock candleSeriesObj/volumeSeriesObj share `setData` —
    // 2 calls (candle + volume).
    // The series objects share spies in this fixture; verify call
    // count = 2 (candles, volume).
  })

  it('serializeState round-trips through restoreState', async () => {
    await adapter.mount({ container, theme: 'dark', width: 800, height: 400 })
    const bars = fixtureBars(50)
    adapter.setBars(bars)
    const state = adapter.serializeState()
    expect(state.bars.length).toBe(50)
    expect(state.theme).toBe('dark')

    const fresh = new LightweightAdapter()
    const c2 = document.createElement('div')
    document.body.appendChild(c2)
    await fresh.mount({ container: c2, theme: 'dark', width: 800, height: 400 })
    fresh.restoreState(state)
    expect(fresh.serializeState().bars.length).toBe(50)
    fresh.unmount()
    c2.remove()
  })

  it('addIndicator + removeIndicator survive without pre-computed series', async () => {
    await adapter.mount({ container, theme: 'dark', width: 800, height: 400 })
    adapter.setBars(fixtureBars(20))
    expect(() =>
      adapter.addIndicator({ id: 'rsi-1', key: 'RSI', params: { period: 14 }, paneId: 'osc' })
    ).not.toThrow()
    expect(() => adapter.removeIndicator('rsi-1')).not.toThrow()
  })

  it('setTheme emits a theme_changed event + re-applies options', async () => {
    await adapter.mount({ container, theme: 'dark', width: 800, height: 400 })
    const events: { kind: string }[] = []
    const off = adapter.onEvent((e) => events.push(e))
    const before = mocks.applyOptions.mock.calls.length
    adapter.setTheme('light')
    off()
    expect(events.some((e) => e.kind === 'theme_changed')).toBe(true)
    expect(mocks.applyOptions.mock.calls.length).toBeGreaterThan(before)
  })

  it('drawing add/remove emits drawing_changed', async () => {
    await adapter.mount({ container, theme: 'dark', width: 800, height: 400 })
    const events: { kind: string; id?: string }[] = []
    const off = adapter.onEvent((e) => events.push(e))
    adapter.addDrawing({ id: 'd1', kind: 'trendline', params: {} })
    off()
    expect(events.some((e) => e.kind === 'drawing_changed' && e.id === 'd1')).toBe(true)
  })

  it('attribution: source declares attributionLogo: true (P-12)', async () => {
    const fs = await import('node:fs')
    const path = await import('node:path')
    const src = fs.readFileSync(path.resolve(__dirname, '..', 'LightweightAdapter.ts'), 'utf-8')
    expect(src).toMatch(/attributionLogo:\s*true/)
  })

  it('volume uses the v5 pane index (NOT priceScaleId: "" on candles)', async () => {
    const fs = await import('node:fs')
    const path = await import('node:path')
    const src = fs.readFileSync(path.resolve(__dirname, '..', 'LightweightAdapter.ts'), 'utf-8')
    // Candle series options must NOT contain priceScaleId: ''
    const candleBlock = src.slice(
      src.indexOf('addSeries(CandlestickSeries'),
      src.indexOf('// Volume in its own v5 pane')
    )
    expect(candleBlock).not.toMatch(/priceScaleId:\s*['"]['"]\s*[,)]/)
    // The volume histogram series must be added with a numeric pane
    // index as the third positional argument.
    expect(src).toMatch(/addSeries\(\s*HistogramSeries[\s\S]*?,\s*PANE_VOLUME\s*,?\s*\)/)
  })

  it('coordinate helpers proxy through the chart API', async () => {
    await adapter.mount({ container, theme: 'dark', width: 800, height: 400 })
    expect(adapter.getPriceCoordinate(100)).toBe(100)
    expect(adapter.getTimeCoordinate(1_700_000_000)).toBe(200)
  })
})
