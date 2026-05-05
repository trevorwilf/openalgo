// Phase 3 — KLineChartProAdapter contract tests.
//
// `klinecharts` is ESM-only and the test environment can't `require()`
// it directly. We mock the module and assert the adapter's contract
// surface (mount/setBars/etc don't throw, state round-trips, native
// indicator names map correctly).

import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import type { NormalizedBar } from '../../../types/bar'
import { utcSeconds } from '../../../types/interval'

vi.mock('klinecharts', () => {
  const applyNewData = vi.fn()
  const updateData = vi.fn()
  const setStyles = vi.fn()
  const createIndicator = vi.fn()
  const removeIndicator = vi.fn()
  const resize = vi.fn()
  const convertToPixel = vi.fn(() => ({ x: 100, y: 200 }))

  const chart = {
    applyNewData,
    updateData,
    setStyles,
    createIndicator,
    removeIndicator,
    resize,
    convertToPixel,
  }
  const init = vi.fn(() => chart)
  const dispose = vi.fn()

  return {
    init,
    dispose,
    __mocks: {
      init,
      dispose,
      applyNewData,
      updateData,
      setStyles,
      createIndicator,
      removeIndicator,
      resize,
      convertToPixel,
    },
  }
})

import * as klinecharts from 'klinecharts'
import { createAdapter, KLineChartProAdapter } from '../KLineChartProAdapter'

const mocks = (klinecharts as unknown as { __mocks: Record<string, ReturnType<typeof vi.fn>> })
  .__mocks

function fixtureBars(count = 200): NormalizedBar[] {
  const t0 = 1_700_000_000
  const out: NormalizedBar[] = []
  let price = 50
  for (let i = 0; i < count; i += 1) {
    const open = price
    const close = price + (i % 4 === 0 ? -0.4 : 0.3)
    const high = Math.max(open, close) + 0.2
    const low = Math.min(open, close) - 0.2
    out.push({
      t: utcSeconds(t0 + i * 60),
      o: String(open),
      h: String(high),
      l: String(low),
      c: String(close),
      v: String(500 + i),
      oi: null,
    })
    price = close
  }
  return out
}

describe('KLineChartProAdapter', () => {
  let container: HTMLElement
  let adapter: KLineChartProAdapter

  beforeEach(() => {
    for (const m of Object.values(mocks)) m.mockClear()
    container = document.createElement('div')
    document.body.appendChild(container)
    adapter = new KLineChartProAdapter()
  })

  afterEach(() => {
    try {
      adapter.unmount()
    } catch {
      /* ignore */
    }
    container.remove()
  })

  it('exposes engineId="klinechart_pro"', () => {
    expect(adapter.engineId).toBe('klinechart_pro')
  })

  it('createAdapter() returns a fresh adapter instance', () => {
    const a = createAdapter()
    expect(a.engineId).toBe('klinechart_pro')
  })

  it('mount calls init with the container', async () => {
    await adapter.mount({ container, theme: 'dark', width: 800, height: 400 })
    expect(mocks.init).toHaveBeenCalledTimes(1)
    expect(mocks.init.mock.calls[0][0]).toBe(container)
  })

  it('setBars(200) calls applyNewData with mapped fixture data', async () => {
    await adapter.mount({ container, theme: 'dark', width: 800, height: 400 })
    adapter.setBars(fixtureBars(200))
    expect(mocks.applyNewData).toHaveBeenCalledTimes(1)
    const data = mocks.applyNewData.mock.calls[0][0] as Array<{ timestamp: number }>
    expect(data.length).toBe(200)
    // klinecharts uses ms timestamps.
    expect(data[0].timestamp).toBe(1_700_000_000 * 1000)
  })

  it('addIndicator with native name proxies createIndicator', async () => {
    await adapter.mount({ container, theme: 'dark', width: 800, height: 400 })
    adapter.setBars(fixtureBars(20))
    adapter.addIndicator({ id: 'ema-1', key: 'EMA', params: { period: 21 }, paneId: 'price' })
    expect(mocks.createIndicator).toHaveBeenCalledTimes(1)
    expect(mocks.createIndicator.mock.calls[0][0]).toBe('EMA')
  })

  it('removeIndicator calls removeIndicator on the chart', async () => {
    await adapter.mount({ container, theme: 'dark', width: 800, height: 400 })
    adapter.setBars(fixtureBars(20))
    adapter.addIndicator({ id: 'ema-1', key: 'EMA', params: { period: 21 }, paneId: 'price' })
    adapter.removeIndicator('ema-1')
    expect(mocks.removeIndicator).toHaveBeenCalledTimes(1)
  })

  it('serializeState retains bars after setBars', async () => {
    await adapter.mount({ container, theme: 'dark', width: 800, height: 400 })
    const bars = fixtureBars(50)
    adapter.setBars(bars)
    const state = adapter.serializeState()
    expect(state.bars.length).toBe(50)
  })

  it('setTheme calls setStyles + emits theme_changed', async () => {
    await adapter.mount({ container, theme: 'dark', width: 800, height: 400 })
    const events: { kind: string }[] = []
    const off = adapter.onEvent((e) => events.push(e))
    const before = mocks.setStyles.mock.calls.length
    adapter.setTheme('light')
    off()
    expect(mocks.setStyles.mock.calls.length).toBe(before + 1)
    expect(events.some((e) => e.kind === 'theme_changed')).toBe(true)
  })

  it('coordinate helpers return numbers when chart returns a point', async () => {
    await adapter.mount({ container, theme: 'dark', width: 800, height: 400 })
    expect(adapter.getPriceCoordinate(100)).toBe(200)
    expect(adapter.getTimeCoordinate(1_700_000_000)).toBe(100)
  })

  it('appendBar after setBars maps to updateData', async () => {
    await adapter.mount({ container, theme: 'dark', width: 800, height: 400 })
    const bars = fixtureBars(10)
    adapter.setBars(bars)
    adapter.appendBar({
      ...bars[bars.length - 1],
      t: utcSeconds((bars[bars.length - 1].t as number) + 60),
    })
    expect(mocks.updateData).toHaveBeenCalledTimes(1)
  })

  it('unmount calls dispose', async () => {
    await adapter.mount({ container, theme: 'dark', width: 800, height: 400 })
    adapter.unmount()
    expect(mocks.dispose).toHaveBeenCalledTimes(1)
  })
})
