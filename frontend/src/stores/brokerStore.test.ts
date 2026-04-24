import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { useBrokerStore } from './brokerStore'

function resetStore() {
  useBrokerStore.setState({
    capabilities: null,
    isLoaded: false,
    isError: false,
    error: null,
  })
}

function mockFetchOk(data: unknown) {
  // @ts-expect-error — override global fetch in test
  global.fetch = vi.fn().mockResolvedValue({
    ok: true,
    status: 200,
    statusText: 'OK',
    json: async () => data,
  })
}

function mockFetchHttpError(status: number, statusText: string) {
  // @ts-expect-error
  global.fetch = vi.fn().mockResolvedValue({
    ok: false,
    status,
    statusText,
    json: async () => ({ status: 'error', message: statusText }),
  })
}

function mockFetchNetworkError(message: string) {
  // @ts-expect-error
  global.fetch = vi.fn().mockRejectedValue(new Error(message))
}

describe('brokerStore.fetchCapabilities', () => {
  beforeEach(() => {
    resetStore()
  })

  afterEach(() => {
    // @ts-expect-error
    delete global.fetch
  })

  it('success populates capabilities and clears error', async () => {
    mockFetchOk({
      status: 'success',
      data: {
        broker_name: 'zerodha',
        broker_type: 'IN_stock',
        supported_exchanges: ['NSE', 'BSE'],
        leverage_config: false,
        broker_code: 'zerodha',
        broker_display_name: 'Zerodha',
        market_families: ['IN_STOCK'],
    supported_regions: ['india'],
        supported_venue_codes: ['NSE', 'BSE'],
        supported_asset_classes: ['EQUITY'],
        supported_order_types: ['MARKET', 'LIMIT'],
        supported_time_in_force: ['DAY'],
        supported_sessions: ['REGULAR'],
        supported_quantity_units: ['WHOLE'],
        trading_currencies: ['INR'],
        base_currency: 'INR',
        supports_fractional: false,
        supports_notional_orders: false,
        supports_extended_hours: false,
        supports_short_selling: false,
        supports_analyzer: true,
        features: {},
      },
    })
    await useBrokerStore.getState().fetchCapabilities()
    const s = useBrokerStore.getState()
    expect(s.capabilities?.broker_code).toBe('zerodha')
    expect(s.isLoaded).toBe(true)
    expect(s.isError).toBe(false)
    expect(s.error).toBeNull()
  })

  it('HTTP error leaves capabilities null and sets isError', async () => {
    mockFetchHttpError(403, 'Forbidden')
    await useBrokerStore.getState().fetchCapabilities()
    const s = useBrokerStore.getState()
    expect(s.capabilities).toBeNull()
    expect(s.isLoaded).toBe(true)
    expect(s.isError).toBe(true)
    expect(s.error).toContain('403')
  })

  it('network error sets isError with message', async () => {
    mockFetchNetworkError('offline')
    await useBrokerStore.getState().fetchCapabilities()
    const s = useBrokerStore.getState()
    expect(s.capabilities).toBeNull()
    expect(s.isError).toBe(true)
    expect(s.error).toContain('offline')
  })

  it('parse error (missing data field) sets isError', async () => {
    mockFetchOk({ status: 'success' /* no data */ })
    await useBrokerStore.getState().fetchCapabilities()
    const s = useBrokerStore.getState()
    expect(s.capabilities).toBeNull()
    expect(s.isError).toBe(true)
  })

  it('invalid status field sets isError', async () => {
    mockFetchOk({ status: 'error', message: 'No broker in session' })
    await useBrokerStore.getState().fetchCapabilities()
    const s = useBrokerStore.getState()
    expect(s.capabilities).toBeNull()
    expect(s.isError).toBe(true)
  })

  it('clearCapabilities resets every field', async () => {
    mockFetchHttpError(500, 'Server Error')
    await useBrokerStore.getState().fetchCapabilities()
    expect(useBrokerStore.getState().isError).toBe(true)

    useBrokerStore.getState().clearCapabilities()
    const s = useBrokerStore.getState()
    expect(s.capabilities).toBeNull()
    expect(s.isLoaded).toBe(false)
    expect(s.isError).toBe(false)
    expect(s.error).toBeNull()
  })

  it('fails closed: no silent fallback when fetch rejects', async () => {
    mockFetchNetworkError('boom')
    await useBrokerStore.getState().fetchCapabilities()
    const s = useBrokerStore.getState()
    // Critical fail-closed assertion: capabilities stay null AND the
    // error is surfaced so consumers CANNOT mistake this for
    // "capabilities loaded successfully with everything supported".
    expect(s.capabilities).toBeNull()
    expect(s.isError).toBe(true)
  })
})
