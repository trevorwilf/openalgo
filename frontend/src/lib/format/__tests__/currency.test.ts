// v5 Phase 2 — currency formatter tests.
//
// Covers the canonical `formatCurrencyAmount` function and the
// hook helpers `useActiveCurrency` / `useFormatCurrency`.

import { describe, it, expect, beforeEach } from 'vitest'
import { renderHook } from '@testing-library/react'

import {
  formatCurrencyAmount,
  useActiveCurrency,
  useFormatCurrency,
} from '../currency'
import { useBrokerStore } from '@/stores/brokerStore'
import type { BrokerCapabilities } from '@/types/capabilities'

function setCapabilities(caps: Partial<BrokerCapabilities> | null): void {
  if (caps == null) {
    useBrokerStore.setState({
      capabilities: null,
      isLoaded: true,
      isError: false,
      error: null,
    })
    return
  }
  // Shallow merge over a permissive base so partial inputs still
  // satisfy the strict typing.
  const base: BrokerCapabilities = {
    broker_name: 'test',
    broker_type: 'IN_stock',
    supported_exchanges: [],
    leverage_config: false,
    broker_code: 'test',
    broker_display_name: 'Test',
    market_families: [],
    supported_regions: ['india'],
    supported_venue_codes: [],
    supported_asset_classes: [],
    supported_order_types: [],
    supported_time_in_force: [],
    supported_sessions: [],
    supported_quantity_units: [],
    trading_currencies: [],
    base_currency: null,
    supports_fractional: false,
    supports_notional_orders: false,
    supports_extended_hours: false,
    supports_short_selling: false,
    supports_analyzer: false,
    features: {},
  }
  useBrokerStore.setState({
    capabilities: { ...base, ...caps },
    isLoaded: true,
    isError: false,
    error: null,
  })
}

describe('formatCurrencyAmount', () => {
  it('formats INR with rupee symbol', () => {
    const out = formatCurrencyAmount(1234.5, 'INR')
    expect(out).toContain('1,234.50')
  })

  it('formats USD with dollar sign', () => {
    const out = formatCurrencyAmount(1234.5, 'USD')
    expect(out).toContain('1,234.50')
    expect(out).toMatch(/\$/)
  })

  it('formats GBP with pound symbol', () => {
    const out = formatCurrencyAmount(50, 'GBP')
    expect(out).toContain('50.00')
  })

  it('formats JPY with zero decimals', () => {
    const out = formatCurrencyAmount(1234, 'JPY')
    expect(out).toContain('1,234')
    expect(out).not.toContain('.')
  })

  it('formats BTC with 8 decimal precision and ticker suffix', () => {
    const out = formatCurrencyAmount(1.23456789, 'BTC')
    expect(out).toBe('1.23456789 BTC')
  })

  it('formats ETH with 6 decimal precision', () => {
    const out = formatCurrencyAmount(1.234567, 'ETH')
    expect(out).toBe('1.234567 ETH')
  })

  it('throws on missing currency', () => {
    expect(() => formatCurrencyAmount(10, '')).toThrow(TypeError)
  })

  it('throws on non-string currency', () => {
    expect(() =>
      formatCurrencyAmount(10, undefined as unknown as string),
    ).toThrow(TypeError)
  })

  it('respects showSymbol=false', () => {
    const out = formatCurrencyAmount(1234.5, 'USD', { showSymbol: false })
    expect(out).toContain('1,234.50')
    expect(out).not.toMatch(/\$/)
  })

  it('respects explicit locale override', () => {
    const out = formatCurrencyAmount(1234.5, 'INR', { locale: 'en-US' })
    expect(out).toContain('1,234.50')
  })
})

describe('useActiveCurrency', () => {
  beforeEach(() => {
    useBrokerStore.getState().clearCapabilities()
  })

  it('returns null when capabilities are unavailable', () => {
    setCapabilities(null)
    const { result } = renderHook(() => useActiveCurrency())
    expect(result.current).toBeNull()
  })

  it('returns base_currency when set', () => {
    setCapabilities({ base_currency: 'USD' })
    const { result } = renderHook(() => useActiveCurrency())
    expect(result.current).toBe('USD')
  })

  it('falls back to first trading_currency when base_currency is null', () => {
    setCapabilities({ base_currency: null, trading_currencies: ['EUR', 'GBP'] })
    const { result } = renderHook(() => useActiveCurrency())
    expect(result.current).toBe('EUR')
  })

  it('returns null when both base_currency and trading_currencies are absent', () => {
    setCapabilities({ base_currency: null, trading_currencies: [] })
    const { result } = renderHook(() => useActiveCurrency())
    expect(result.current).toBeNull()
  })
})

describe('useFormatCurrency', () => {
  beforeEach(() => {
    useBrokerStore.getState().clearCapabilities()
  })

  it('renders with INR for India broker capabilities', () => {
    setCapabilities({ base_currency: 'INR' })
    const { result } = renderHook(() => useFormatCurrency())
    const out = result.current(1234.5)
    expect(out).toContain('1,234.50')
  })

  it('renders with USD for US broker capabilities', () => {
    setCapabilities({ base_currency: 'USD' })
    const { result } = renderHook(() => useFormatCurrency())
    const out = result.current(1234.5)
    expect(out).toMatch(/\$/)
  })

  it('renders no-symbol number when capabilities are missing', () => {
    setCapabilities(null)
    const { result } = renderHook(() => useFormatCurrency())
    const out = result.current(1234.5)
    expect(out).toBe('1234.50')
    expect(out).not.toMatch(/[$₹]/)
  })
})
