// v6 Phase 1 — useVenueTimezone hook re-export tests.

import { describe, expect, it, beforeEach } from 'vitest'
import { renderHook } from '@testing-library/react'

import {
  useVenueTimezone,
  useVenueTimezoneLabel,
  venueTimezoneShortLabel,
} from './useVenueTimezone'
import { useBrokerStore } from '@/stores/brokerStore'
import type { BrokerCapabilities } from '@/types/capabilities'

function setFeatures(features: Record<string, unknown> | null): void {
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
    features: features as Record<string, boolean>,
  }
  useBrokerStore.setState({
    capabilities: base,
    isLoaded: true,
    isError: false,
    error: null,
  })
}

describe('useVenueTimezone (v6 Phase 1 re-export)', () => {
  beforeEach(() => {
    setFeatures(null)
  })

  it('returns null when no broker is connected', () => {
    setFeatures(null)
    const { result } = renderHook(() => useVenueTimezone())
    expect(result.current).toBeNull()
  })

  it('reads capabilities.features.timezone for India brokers', () => {
    setFeatures({ timezone: 'Asia/Kolkata' })
    const { result } = renderHook(() => useVenueTimezone())
    expect(result.current).toBe('Asia/Kolkata')
  })

  it('reads capabilities.features.timezone for US brokers', () => {
    setFeatures({ timezone: 'America/New_York' })
    const { result } = renderHook(() => useVenueTimezone())
    expect(result.current).toBe('America/New_York')
  })

  it('falls back to capabilities.features.venue_timezone when timezone is missing', () => {
    setFeatures({ venue_timezone: 'Europe/London' })
    const { result } = renderHook(() => useVenueTimezone())
    expect(result.current).toBe('Europe/London')
  })

  it('returns null when both timezone keys are missing', () => {
    setFeatures({ irrelevant: 'value' })
    const { result } = renderHook(() => useVenueTimezone())
    expect(result.current).toBeNull()
  })

  it('useVenueTimezoneLabel returns the short display label', () => {
    setFeatures({ timezone: 'Asia/Kolkata' })
    const { result } = renderHook(() => useVenueTimezoneLabel())
    expect(result.current).toBe('IST')
  })

  it('useVenueTimezoneLabel returns ET for America/New_York', () => {
    setFeatures({ timezone: 'America/New_York' })
    const { result } = renderHook(() => useVenueTimezoneLabel())
    expect(result.current).toBe('ET')
  })

  it('useVenueTimezoneLabel falls back to the IANA name for unknown zones', () => {
    setFeatures({ timezone: 'Pacific/Honolulu' })
    const { result } = renderHook(() => useVenueTimezoneLabel())
    expect(result.current).toBe('Pacific/Honolulu')
  })

  it('venueTimezoneShortLabel pure helper returns null for null/undefined input', () => {
    expect(venueTimezoneShortLabel(null)).toBeNull()
    expect(venueTimezoneShortLabel(undefined)).toBeNull()
  })

  it('venueTimezoneShortLabel pure helper returns IST for Asia/Kolkata', () => {
    expect(venueTimezoneShortLabel('Asia/Kolkata')).toBe('IST')
  })
})
