import { renderHook } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it } from 'vitest'
import { useBrokerStore } from '@/stores/brokerStore'
import type { BrokerCapabilities } from '@/types/capabilities'
import { LEGACY_FALLBACK_EXCHANGES } from '@/lib/india_legacy/legacy_fallback_exchanges'
import { useSupportedExchanges } from './useSupportedExchanges'

// Phase 1 v3 (ADR 0017) — verify the literal containment refactor
// preserves behavior. The hook used to define LEGACY_FALLBACK_EXCHANGES
// inline; it now imports from `@/lib/india_legacy/...`. The downstream
// behavior must remain bit-identical.

function setCapabilities(cap: Partial<BrokerCapabilities> | null) {
  const base: BrokerCapabilities = {
    broker_name: 'zerodha',
    broker_type: 'IN_stock',
    supported_exchanges: ['NSE', 'BSE', 'NFO'],
    leverage_config: false,
    broker_code: 'zerodha',
    broker_display_name: 'Zerodha',
    market_families: ['IN_STOCK'],
    supported_regions: ['india'],
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

describe('useSupportedExchanges literal containment (ADR 0017)', () => {
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

  it('LEGACY_FALLBACK_EXCHANGES is exported from the india_legacy module', () => {
    expect(Array.isArray(LEGACY_FALLBACK_EXCHANGES)).toBe(true)
    expect(LEGACY_FALLBACK_EXCHANGES).toContain('NSE')
    expect(LEGACY_FALLBACK_EXCHANGES).toContain('BSE')
    expect(LEGACY_FALLBACK_EXCHANGES).toContain('CRYPTO')
  })

  it('non-India broker → empty exchange list (no fallback)', () => {
    setCapabilities({
      broker_name: 'alpaca',
      broker_type: 'US_stock',
      broker_code: 'alpaca',
      market_families: ['US_STOCK'],
      supported_regions: ['us'],
      supported_venue_codes: [],
      supported_exchanges: [],
      base_currency: 'USD',
      trading_currencies: ['USD'],
    })
    const { result } = renderHook(() =>
      useSupportedExchanges({ allowLegacyFallback: true }),
    )
    expect(result.current.tradingExchanges).toEqual([])
  })

  it('India broker without venue codes → uses LEGACY_FALLBACK_EXCHANGES', () => {
    useBrokerStore.setState({ capabilities: null, isLoaded: false })
    const { result } = renderHook(() =>
      useSupportedExchanges({ allowLegacyFallback: true }),
    )
    const labels = result.current.tradingExchanges.map((e) => e.value)
    // Every value in tradingExchanges must come from LEGACY_FALLBACK_EXCHANGES
    // (minus the _INDEX-suffixed entries which the hook filters out).
    for (const v of labels) {
      expect(LEGACY_FALLBACK_EXCHANGES).toContain(v)
    }
    expect(result.current.isFallback).toBe(true)
  })

  it('unknown broker (capabilities loaded but error) → empty list with retry state', () => {
    useBrokerStore.setState({
      capabilities: null,
      isLoaded: true,
      isError: true,
      error: 'HTTP 500',
    })
    const { result } = renderHook(() =>
      useSupportedExchanges({ allowLegacyFallback: false }),
    )
    expect(result.current.isError).toBe(true)
    expect(result.current.tradingExchanges).toEqual([])
  })
})
