import { describe, expect, it } from 'vitest'
import {
  type BrokerCapabilities,
  hasCapability,
  isOrderTypeSupported,
  isSessionSupported,
  isTimeInForceSupported,
  platformOrderTypeToLegacy,
} from './capabilities'

function cap(overrides: Partial<BrokerCapabilities> = {}): BrokerCapabilities {
  return {
    broker_name: 'zerodha',
    broker_type: 'IN_stock',
    supported_exchanges: ['NSE', 'BSE', 'NFO'],
    leverage_config: false,
    broker_code: 'zerodha',
    broker_display_name: 'Zerodha',
    market_families: ['IN_STOCK'],
    supported_venue_codes: ['NSE', 'BSE', 'NFO'],
    supported_asset_classes: ['EQUITY', 'FUTURE', 'OPTION', 'INDEX', 'ETF'],
    supported_order_types: ['MARKET', 'LIMIT', 'STOP', 'STOP_LIMIT'],
    supported_time_in_force: ['DAY'],
    supported_sessions: ['REGULAR'],
    supported_quantity_units: ['WHOLE', 'LOTS'],
    trading_currencies: ['INR'],
    base_currency: 'INR',
    supports_fractional: false,
    supports_notional_orders: false,
    supports_extended_hours: false,
    supports_short_selling: false,
    supports_analyzer: true,
    features: {},
    ...overrides,
  }
}

describe('isOrderTypeSupported', () => {
  it('returns true when order type is listed', () => {
    expect(isOrderTypeSupported(cap(), 'MARKET')).toBe(true)
    expect(isOrderTypeSupported(cap(), 'LIMIT')).toBe(true)
  })

  it('returns false when order type is not listed', () => {
    expect(isOrderTypeSupported(cap(), 'TRAILING_STOP')).toBe(false)
    expect(isOrderTypeSupported(cap(), 'MARKET_ON_OPEN')).toBe(false)
  })

  it('returns false for null capabilities', () => {
    expect(isOrderTypeSupported(null, 'MARKET')).toBe(false)
  })
})

describe('isTimeInForceSupported', () => {
  it('Indian broker supports only DAY', () => {
    expect(isTimeInForceSupported(cap(), 'DAY')).toBe(true)
    expect(isTimeInForceSupported(cap(), 'GTC')).toBe(false)
  })

  it('crypto broker supports DAY + GTC + IOC + FOK', () => {
    const crypto = cap({
      broker_type: 'crypto',
      supported_time_in_force: ['DAY', 'GTC', 'IOC', 'FOK'],
    })
    expect(isTimeInForceSupported(crypto, 'GTC')).toBe(true)
    expect(isTimeInForceSupported(crypto, 'GTD')).toBe(false)
  })

  it('returns false for null capabilities', () => {
    expect(isTimeInForceSupported(null, 'DAY')).toBe(false)
  })
})

describe('isSessionSupported', () => {
  it('Indian broker supports only REGULAR', () => {
    expect(isSessionSupported(cap(), 'REGULAR')).toBe(true)
    expect(isSessionSupported(cap(), 'PRE_MARKET')).toBe(false)
  })

  it('crypto broker supports ALL_DAY', () => {
    const crypto = cap({ supported_sessions: ['ALL_DAY'] })
    expect(isSessionSupported(crypto, 'ALL_DAY')).toBe(true)
    expect(isSessionSupported(crypto, 'REGULAR')).toBe(false)
  })
})

describe('hasCapability', () => {
  it('respects first-class flags', () => {
    expect(hasCapability(cap(), 'supports_analyzer')).toBe(true)
    expect(hasCapability(cap(), 'supports_fractional')).toBe(false)
    const frac = cap({ supports_fractional: true })
    expect(hasCapability(frac, 'supports_fractional')).toBe(true)
  })

  it('null capabilities → every flag is false', () => {
    expect(hasCapability(null, 'supports_analyzer')).toBe(false)
    expect(hasCapability(null, 'leverage_config')).toBe(false)
  })
})

describe('platformOrderTypeToLegacy', () => {
  it('maps the 4 legacy-expressible types', () => {
    expect(platformOrderTypeToLegacy('MARKET')).toBe('MARKET')
    expect(platformOrderTypeToLegacy('LIMIT')).toBe('LIMIT')
    expect(platformOrderTypeToLegacy('STOP')).toBe('SL-M')
    expect(platformOrderTypeToLegacy('STOP_LIMIT')).toBe('SL')
  })

  it('returns null for order types the legacy API cannot express', () => {
    expect(platformOrderTypeToLegacy('TRAILING_STOP')).toBeNull()
    expect(platformOrderTypeToLegacy('MARKET_ON_OPEN')).toBeNull()
    expect(platformOrderTypeToLegacy('MARKET_ON_CLOSE')).toBeNull()
    expect(platformOrderTypeToLegacy('LIMIT_ON_OPEN')).toBeNull()
    expect(platformOrderTypeToLegacy('LIMIT_ON_CLOSE')).toBeNull()
    expect(platformOrderTypeToLegacy('PEGGED')).toBeNull()
  })
})
