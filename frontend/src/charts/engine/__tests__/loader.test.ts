import { afterEach, describe, expect, it, vi } from 'vitest'
import type { ChartEngineAdapter } from '../ChartEngineAdapter'
import {
  loadEngine,
  resetAdapterImportersForTests,
  setAdapterImporters,
  setTradingViewSdkAvailability,
} from '../loader'

function fakeAdapter(id: ChartEngineAdapter['engineId'] = 'lightweight'): ChartEngineAdapter {
  return {
    engineId: id,
    mount: vi.fn(async () => undefined),
    unmount: vi.fn(),
    setBars: vi.fn(),
    appendBar: vi.fn(),
    updateForming: vi.fn(),
    addIndicator: vi.fn(),
    updateIndicator: vi.fn(),
    removeIndicator: vi.fn(),
    addDrawing: vi.fn(),
    removeDrawing: vi.fn(),
    setTheme: vi.fn(),
    resize: vi.fn(),
    onEvent: vi.fn(() => () => undefined),
    serializeState: vi.fn(() => ({
      bars: [],
      panes: [],
      indicators: [],
      drawings: [],
      theme: 'dark',
    })),
    restoreState: vi.fn(),
    getPriceCoordinate: vi.fn(() => 0),
    getTimeCoordinate: vi.fn(() => 0),
  }
}

describe('engine loader', () => {
  afterEach(() => {
    resetAdapterImportersForTests()
    vi.restoreAllMocks()
  })

  it('default request resolves to lightweight (when importer is wired)', async () => {
    setAdapterImporters({
      loadLightweight: async () => ({ createAdapter: () => fakeAdapter('lightweight') }),
    })
    const result = await loadEngine('lightweight')
    expect(result.resolved).toBe('lightweight')
    expect(result.fallback).toBeNull()
    expect(result.adapter.engineId).toBe('lightweight')
  })

  it('klinechart_pro resolves to klinechart_pro when wired', async () => {
    setAdapterImporters({
      loadKlineChartPro: async () => ({
        createAdapter: () => fakeAdapter('klinechart_pro'),
      }),
    })
    const result = await loadEngine('klinechart_pro')
    expect(result.resolved).toBe('klinechart_pro')
  })

  it('falls back to lightweight when Advanced Charts SDK files are absent (default probe)', async () => {
    const warn = vi.spyOn(console, 'warn').mockImplementation(() => undefined)
    setAdapterImporters({
      loadLightweight: async () => ({ createAdapter: () => fakeAdapter('lightweight') }),
    })
    // SDK probe returns false by default.
    const result = await loadEngine('tradingview_advanced')
    expect(result.requested).toBe('tradingview_advanced')
    expect(result.resolved).toBe('lightweight')
    expect(result.fallback).toEqual({
      from: 'tradingview_advanced',
      reason: 'sdk_absent',
    })
    expect(warn).toHaveBeenCalledTimes(1)
    expect(warn.mock.calls[0][0]).toMatch(/Advanced Charts files missing/)
  })

  it('uses Advanced Charts adapter when the SDK probe returns true', async () => {
    setTradingViewSdkAvailability(() => true)
    setAdapterImporters({
      loadAdvanced: async () => ({
        createAdapter: () => fakeAdapter('tradingview_advanced'),
      }),
    })
    const result = await loadEngine('tradingview_advanced')
    expect(result.resolved).toBe('tradingview_advanced')
    expect(result.fallback).toBeNull()
  })

  it('preserves per-cell engine selection (resolved string is what was requested)', async () => {
    setAdapterImporters({
      loadLightweight: async () => ({ createAdapter: () => fakeAdapter('lightweight') }),
      loadKlineChartPro: async () => ({
        createAdapter: () => fakeAdapter('klinechart_pro'),
      }),
    })
    const a = await loadEngine('lightweight')
    const b = await loadEngine('klinechart_pro')
    expect(a.resolved).toBe('lightweight')
    expect(b.resolved).toBe('klinechart_pro')
  })
})
