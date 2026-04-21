import { renderHook } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it } from 'vitest'
import { useBrokerStore } from '@/stores/brokerStore'
import type { BrokerCapabilities } from '@/types/capabilities'
import { useSupportedExchanges } from './useSupportedExchanges'

function setCapabilities(cap: Partial<BrokerCapabilities> | null) {
  const base: BrokerCapabilities = {
    broker_name: 'zerodha',
    broker_type: 'IN_stock',
    supported_exchanges: ['NSE', 'BSE', 'NFO'],
    leverage_config: false,
    broker_code: 'zerodha',
    broker_display_name: 'Zerodha',
    market_families: ['IN_STOCK'],
    supported_venue_codes: ['NSE', 'BSE', 'NFO'],
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
  }
  useBrokerStore.setState({
    capabilities: cap === null ? null : { ...base, ...cap },
    isLoaded: true,
    isError: false,
    error: null,
  })
}

describe('useSupportedExchanges', () => {
  beforeEach(() => {
    setCapabilities(null)
    useBrokerStore.setState({ isLoaded: false, isError: false })
  })

  afterEach(() => {
    useBrokerStore.setState({
      capabilities: null,
      isLoaded: false,
      isError: false,
      error: null,
    })
  })

  it('returns supported_venue_codes when capabilities are loaded', () => {
    setCapabilities({ supported_venue_codes: ['NSE', 'BSE'] })
    const { result } = renderHook(() => useSupportedExchanges())
    expect(result.current.tradingExchanges.map((e) => e.value)).toEqual(['NSE', 'BSE'])
    expect(result.current.isFallback).toBe(false)
    expect(result.current.isError).toBe(false)
  })

  it('surfaces isError when the store has an error state', () => {
    useBrokerStore.setState({
      capabilities: null,
      isLoaded: true,
      isError: true,
      error: 'HTTP 500',
    })
    const { result } = renderHook(() => useSupportedExchanges({ allowLegacyFallback: false }))
    expect(result.current.isError).toBe(true)
    expect(result.current.tradingExchanges).toEqual([])
  })

  it('fallback opt-in returns the hardcoded list', () => {
    useBrokerStore.setState({ capabilities: null, isLoaded: false })
    const { result } = renderHook(() => useSupportedExchanges({ allowLegacyFallback: true }))
    expect(result.current.tradingExchanges.map((e) => e.value)).toContain('NSE')
    expect(result.current.isFallback).toBe(true)
  })

  it('fallback defaults to true for backward compatibility', () => {
    useBrokerStore.setState({ capabilities: null, isLoaded: false })
    const { result } = renderHook(() => useSupportedExchanges())
    expect(result.current.isFallback).toBe(true)
    expect(result.current.tradingExchanges.map((e) => e.value).length).toBeGreaterThan(0)
  })

  it('explicit allowLegacyFallback=false returns empty when unavailable', () => {
    useBrokerStore.setState({ capabilities: null, isLoaded: false })
    const { result } = renderHook(() => useSupportedExchanges({ allowLegacyFallback: false }))
    expect(result.current.tradingExchanges).toEqual([])
    expect(result.current.allExchanges).toEqual([])
  })

  it('fnoExchanges filters to NFO/BFO/MCX/CDS/CRYPTO', () => {
    setCapabilities({
      supported_venue_codes: ['NSE', 'NFO', 'BSE', 'BFO', 'MCX', 'NSE_INDEX'],
    })
    const { result } = renderHook(() => useSupportedExchanges())
    expect(result.current.fnoExchanges.map((e) => e.value).sort()).toEqual(['BFO', 'MCX', 'NFO'])
  })

  it('toolsFnoExchanges excludes MCX and CDS', () => {
    setCapabilities({
      supported_venue_codes: ['NFO', 'BFO', 'MCX', 'CDS', 'CRYPTO'],
    })
    const { result } = renderHook(() => useSupportedExchanges())
    expect(result.current.toolsFnoExchanges.map((e) => e.value).sort()).toEqual([
      'BFO',
      'CRYPTO',
      'NFO',
    ])
  })

  it('crypto broker: isCrypto true, default exchange CRYPTO', () => {
    setCapabilities({
      broker_type: 'crypto',
      supported_venue_codes: ['CRYPTO'],
    })
    const { result } = renderHook(() => useSupportedExchanges())
    expect(result.current.isCrypto).toBe(true)
    expect(result.current.defaultExchange).toBe('CRYPTO')
  })
})
