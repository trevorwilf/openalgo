// Phase 3 — loader fallback path explicit test.
//
// Covers §0.3 "engine === 'tradingview_advanced' AND SDK absent →
// log warn + fall through to lightweight". Phase 2 already ships a
// loader test with the same coverage; this file makes the contract
// explicit so a future refactor that breaks the fallback path is
// caught with a name that matches HANDOFF §0.3.

import { afterEach, describe, expect, it, vi } from 'vitest'
import {
  loadEngine,
  resetAdapterImportersForTests,
  setAdapterImporters,
  setTradingViewSdkAvailability,
} from '../loader'

afterEach(() => {
  resetAdapterImportersForTests()
  vi.restoreAllMocks()
})

describe('loader: Advanced Charts fallback (§0.3)', () => {
  it('falls back to lightweight + console.warn when SDK probe returns false', async () => {
    const warn = vi.spyOn(console, 'warn').mockImplementation(() => undefined)
    setAdapterImporters({
      loadLightweight: async () => ({
        createAdapter: () => makeFake('lightweight'),
      }),
    })
    const result = await loadEngine('tradingview_advanced')
    expect(result.requested).toBe('tradingview_advanced')
    expect(result.resolved).toBe('lightweight')
    expect(result.fallback).toEqual({
      from: 'tradingview_advanced',
      reason: 'sdk_absent',
    })
    expect(warn).toHaveBeenCalledWith(
      'Advanced Charts files missing; falling back to Lightweight Charts'
    )
  })

  it('honors explicit SDK availability override (yes branch)', async () => {
    setTradingViewSdkAvailability(() => true)
    setAdapterImporters({
      loadAdvanced: async () => ({
        createAdapter: () => makeFake('tradingview_advanced'),
      }),
    })
    const result = await loadEngine('tradingview_advanced')
    expect(result.resolved).toBe('tradingview_advanced')
    expect(result.fallback).toBeNull()
  })
})

function makeFake(id: 'lightweight' | 'klinechart_pro' | 'tradingview_advanced') {
  return {
    engineId: id,
    mount: async () => undefined,
    unmount: () => undefined,
    setBars: () => undefined,
    appendBar: () => undefined,
    updateForming: () => undefined,
    addIndicator: () => undefined,
    updateIndicator: () => undefined,
    removeIndicator: () => undefined,
    addDrawing: () => undefined,
    removeDrawing: () => undefined,
    setTheme: () => undefined,
    resize: () => undefined,
    onEvent: () => () => undefined,
    serializeState: () => ({
      bars: [],
      panes: [],
      indicators: [],
      drawings: [],
      theme: 'dark' as const,
    }),
    restoreState: () => undefined,
    getPriceCoordinate: () => null,
    getTimeCoordinate: () => null,
  }
}
