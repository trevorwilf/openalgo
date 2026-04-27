// v5 Phase 2 — timezone helper tests.

import { describe, expect, it, beforeEach } from 'vitest'
import { renderHook } from '@testing-library/react'

import {
  timezoneShortLabel,
  useActiveTimezone,
  useActiveTimezoneLabel,
} from '../timezone'
import { useBrokerStore } from '@/stores/brokerStore'
import type { BrokerCapabilities } from '@/types/capabilities'

function setCapabilities(features: Record<string, unknown> | null): void {
  if (features === null) {
    useBrokerStore.setState({
      capabilities: null,
      isLoaded: true,
      isError: false,
      error: null,
    })
    return
  }
  const base: BrokerCapabilities = {
    broker_name: 'test',
    broker_type: 'IN_stock',
    supported_exchanges: [],
    leverage_config: false,
    broker_code: 'test',
    broker_display_name: 'Test',
    market_families: [],
    supported_regions: [],
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
    features: features as Record<string, boolean>, // tests may pass strings
  }
  useBrokerStore.setState({
    capabilities: base,
    isLoaded: true,
    isError: false,
    error: null,
  })
}

describe('timezoneShortLabel', () => {
  it('renders India IANA tz as IST', () => {
    expect(timezoneShortLabel('Asia/Kolkata')).toBe('IST')
  })

  it('renders NY IANA tz as ET', () => {
    expect(timezoneShortLabel('America/New_York')).toBe('ET')
  })

  it('falls back to the IANA name for unknown tz', () => {
    expect(timezoneShortLabel('Pacific/Auckland')).toBe('Pacific/Auckland')
  })

  it('returns null for null/undefined', () => {
    expect(timezoneShortLabel(null)).toBeNull()
    expect(timezoneShortLabel(undefined)).toBeNull()
    expect(timezoneShortLabel('')).toBeNull()
  })
})

describe('useActiveTimezone', () => {
  beforeEach(() => {
    useBrokerStore.getState().clearCapabilities()
  })

  it('returns null when capabilities are missing', () => {
    setCapabilities(null)
    const { result } = renderHook(() => useActiveTimezone())
    expect(result.current).toBeNull()
  })

  it('returns features.timezone when present', () => {
    setCapabilities({ timezone: 'Asia/Kolkata' })
    const { result } = renderHook(() => useActiveTimezone())
    expect(result.current).toBe('Asia/Kolkata')
  })

  it('falls back to features.venue_timezone', () => {
    setCapabilities({ venue_timezone: 'America/New_York' })
    const { result } = renderHook(() => useActiveTimezone())
    expect(result.current).toBe('America/New_York')
  })

  it('returns null when neither key is present', () => {
    setCapabilities({})
    const { result } = renderHook(() => useActiveTimezone())
    expect(result.current).toBeNull()
  })
})

describe('useActiveTimezoneLabel', () => {
  beforeEach(() => {
    useBrokerStore.getState().clearCapabilities()
  })

  it('returns the display label for a known IANA tz', () => {
    setCapabilities({ timezone: 'Europe/London' })
    const { result } = renderHook(() => useActiveTimezoneLabel())
    expect(result.current).toBe('GB')
  })

  it('returns the raw IANA name for unknown tz', () => {
    setCapabilities({ timezone: 'Pacific/Auckland' })
    const { result } = renderHook(() => useActiveTimezoneLabel())
    expect(result.current).toBe('Pacific/Auckland')
  })

  it('returns null when no timezone resolved', () => {
    setCapabilities(null)
    const { result } = renderHook(() => useActiveTimezoneLabel())
    expect(result.current).toBeNull()
  })
})
