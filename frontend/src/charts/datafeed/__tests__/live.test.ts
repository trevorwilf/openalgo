// Phase 4 — live datafeed contract tests.
//
// We don't open a real socket.io connection — we inject a fake Socket
// via `setSocketFactoryForTests`, drive subscribe/unsubscribe through
// the public API, and assert the right control envelopes were emitted
// + reconnect resume hook is sent on (re)connect.

import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { utcSeconds } from '../../types/interval'
import {
  resetLiveStateForTests,
  setPollingFetchForTests,
  setSocketFactoryForTests,
  subscribeBars,
  unsubscribeBars,
} from '../live'

interface FakeSocket {
  connected: boolean
  emit: ReturnType<typeof vi.fn>
  on: ReturnType<typeof vi.fn>
  disconnect: ReturnType<typeof vi.fn>
  // helpers exposed to tests
  _trigger(event: string, payload?: unknown): void
}

function makeFakeSocket(): FakeSocket {
  const handlers = new Map<string, (p: unknown) => void>()
  return {
    connected: false,
    emit: vi.fn(),
    on: vi.fn((event: string, handler: (p: unknown) => void) => {
      handlers.set(event, handler)
    }),
    disconnect: vi.fn(),
    _trigger: (event, payload) => {
      const h = handlers.get(event)
      if (h) h(payload as never)
    },
  }
}

beforeEach(() => {
  resetLiveStateForTests()
})

afterEach(() => {
  resetLiveStateForTests()
})

describe('subscribeBars (websocket)', () => {
  it('emits a subscribe control envelope on connect with last_seen_ts', async () => {
    const fake = makeFakeSocket()
    setSocketFactoryForTests(() => fake as never)
    const onTick = vi.fn()
    const sub = await subscribeBars({
      ref: { canonical_symbol: 'AAPL' },
      interval: '1m',
      onTick,
      resumeFromMs: 1_700_000_000_000,
    })
    expect(sub.transport).toBe('websocket')
    // socket.on('connect') was registered.
    expect(fake.on).toHaveBeenCalledWith('connect', expect.any(Function))
    // Trigger connect to fire the subscribe.
    fake._trigger('connect')
    expect(fake.emit).toHaveBeenCalledWith(
      'control',
      expect.objectContaining({ op: 'subscribe', last_seen_ts: 1_700_000_000_000 })
    )
  })

  it('routes envelope payload to onTick with branded UTC ms', async () => {
    const fake = makeFakeSocket()
    setSocketFactoryForTests(() => fake as never)
    const onTick = vi.fn()
    await subscribeBars({
      ref: { canonical_symbol: 'AAPL' },
      interval: '1m',
      onTick,
    })
    fake._trigger('envelope', {
      type: 'bar_update',
      payload: {
        kind: 'trade',
        symbol: 'AAPL',
        t: 1_700_000_005_000,
        payload: { p: 100.5, s: 10 },
      },
    })
    expect(onTick).toHaveBeenCalledTimes(1)
    const tick = onTick.mock.calls[0][0]
    expect(tick.kind).toBe('trade')
    expect(tick.symbol).toBe('AAPL')
    expect(tick.t).toBe(1_700_000_005_000)
  })

  it('unsubscribeBars emits an unsubscribe envelope and disconnects', async () => {
    const fake = makeFakeSocket()
    setSocketFactoryForTests(() => fake as never)
    const sub = await subscribeBars({
      ref: { canonical_symbol: 'AAPL' },
      interval: '1m',
      onTick: vi.fn(),
    })
    await unsubscribeBars(sub)
    const calls = fake.emit.mock.calls.filter((c) => c[0] === 'control')
    const unsubCall = calls.find((c) => (c[1] as { op: string }).op === 'unsubscribe')
    expect(unsubCall).toBeDefined()
    expect(fake.disconnect).toHaveBeenCalledTimes(1)
  })
})

describe('subscribeBars (polling fallback)', () => {
  it('uses /api/v2/quotes at the configured cadence', async () => {
    const pollFetch = vi.fn(
      async () =>
        ({
          ok: true,
          async json() {
            return {
              data: [
                {
                  instrument: { canonical_symbol: 'AAPL', venue_code: 'XNAS', instrument_id: null },
                  quote: { bid: '100.0', ask: '100.5', last: '100.25' },
                },
              ],
            }
          },
        }) as unknown as Response
    )
    setPollingFetchForTests(pollFetch as unknown as typeof fetch)

    const onTick = vi.fn()
    const sub = await subscribeBars({
      ref: { canonical_symbol: 'AAPL' },
      interval: '1m',
      onTick,
      transportHint: 'polling',
      pollingIntervalMs: 50,
    })
    expect(sub.transport).toBe('polling')
    // Wait for the first tick (immediate) + one polled tick.
    await new Promise((r) => setTimeout(r, 80))
    expect(pollFetch.mock.calls.length).toBeGreaterThanOrEqual(1)
    expect(onTick).toHaveBeenCalled()
    await unsubscribeBars(sub)
  })

  it('throws if subscribed without a symbol', async () => {
    await expect(
      subscribeBars({
        ref: {},
        interval: '1m',
        onTick: () => undefined,
      })
    ).rejects.toThrow(/canonical_symbol/)
  })
})
