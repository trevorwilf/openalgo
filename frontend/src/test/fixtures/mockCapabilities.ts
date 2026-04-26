// Phase 6 v4 (ADR 0023) — multi-region capability fixtures.
//
// Used by frontend component tests to assert capability-driven UI
// rendering for IN / US / EU / UK brokers without depending on the
// real /api/v2/capabilities endpoint.
//
// New capability-driven components MUST cover at least:
//   * the India fixture (legacy parity)
//   * the US fixture (no India literals appear in rendered DOM)
//   * the unsupported fixture (component renders an unavailable state)
//
// Keep these fixtures small and stable — adding a new field requires
// updating every mock here so the contract remains uniform.

export interface MockBrokerCapabilities {
  broker_code: string
  broker_display_name: string
  broker_type: string
  supported_regions: string[]
  market_families: string[]
  supported_venue_codes: string[]
  supported_asset_classes: string[]
  supported_order_types: string[]
  supported_time_in_force: string[]
  supported_sessions: string[]
  supported_quantity_units: string[]
  trading_currencies: string[]
  default_currency: string
  base_currency: string
  supports_extended_hours?: boolean
  supports_short_selling?: boolean
  supports_combo_types?: string[]
}

export const INDIA_CAPABILITIES_FIXTURE: MockBrokerCapabilities = {
  broker_code: 'zerodha',
  broker_display_name: 'Zerodha',
  broker_type: 'IN_stock',
  supported_regions: ['india'],
  market_families: ['IN_STOCK'],
  supported_venue_codes: ['NSE', 'BSE', 'NFO', 'BFO', 'CDS', 'MCX'],
  supported_asset_classes: ['EQUITY', 'OPTION', 'FUTURE'],
  supported_order_types: ['MARKET', 'LIMIT', 'SL', 'SL-M'],
  supported_time_in_force: ['DAY'],
  supported_sessions: ['REGULAR'],
  supported_quantity_units: ['WHOLE'],
  trading_currencies: ['INR'],
  default_currency: 'INR',
  base_currency: 'INR',
  supports_extended_hours: false,
  supports_short_selling: false,
}

export const US_CAPABILITIES_FIXTURE: MockBrokerCapabilities = {
  broker_code: '_mock_schwab_like',
  broker_display_name: 'Mock Schwab-Like',
  broker_type: 'US_stock',
  supported_regions: ['us'],
  market_families: ['US_STOCK'],
  supported_venue_codes: ['XNYS', 'XNAS', 'ARCX', 'BATS', 'IEXG'],
  supported_asset_classes: ['EQUITY', 'ETF', 'OPTION'],
  supported_order_types: ['MARKET', 'LIMIT', 'STOP', 'STOP_LIMIT', 'TRAILING_STOP'],
  supported_time_in_force: ['DAY', 'GTC', 'GTD', 'FOK', 'IOC'],
  supported_sessions: ['REGULAR', 'PRE_MARKET', 'POST_MARKET'],
  supported_quantity_units: ['WHOLE', 'FRACTIONAL', 'NOTIONAL'],
  trading_currencies: ['USD'],
  default_currency: 'USD',
  base_currency: 'USD',
  supports_extended_hours: true,
  supports_short_selling: true,
  supports_combo_types: ['SINGLE', 'OTO', 'OCO', 'OTOCO', 'COMBO', 'MULTILEG_OPTIONS'],
}

export const EU_CAPABILITIES_FIXTURE: MockBrokerCapabilities = {
  broker_code: 'mock_eu_broker',
  broker_display_name: 'Mock EU Broker',
  broker_type: 'EU_stock',
  supported_regions: ['eu'],
  market_families: ['EU_STOCK'],
  supported_venue_codes: ['XPAR', 'XETR'],
  supported_asset_classes: ['EQUITY', 'ETF'],
  supported_order_types: ['MARKET', 'LIMIT'],
  supported_time_in_force: ['DAY', 'GTC'],
  supported_sessions: ['REGULAR', 'OPENING_AUCTION', 'CLOSING_AUCTION'],
  supported_quantity_units: ['WHOLE'],
  trading_currencies: ['EUR'],
  default_currency: 'EUR',
  base_currency: 'EUR',
  supports_extended_hours: false,
  supports_short_selling: false,
}

export const UK_CAPABILITIES_FIXTURE: MockBrokerCapabilities = {
  broker_code: 'mock_uk_broker',
  broker_display_name: 'Mock UK Broker',
  broker_type: 'UK_stock',
  supported_regions: ['uk'],
  market_families: ['UK_STOCK'],
  supported_venue_codes: ['XLON'],
  supported_asset_classes: ['EQUITY', 'ETF'],
  supported_order_types: ['MARKET', 'LIMIT'],
  supported_time_in_force: ['DAY', 'GTC'],
  supported_sessions: ['REGULAR', 'OPENING_AUCTION', 'CLOSING_AUCTION'],
  supported_quantity_units: ['WHOLE'],
  trading_currencies: ['GBP'],
  default_currency: 'GBP',
  base_currency: 'GBP',
  supports_extended_hours: false,
  supports_short_selling: false,
}

export const UNSUPPORTED_CAPABILITIES_FIXTURE = null

export const ALL_CAPABILITIES_FIXTURES = {
  india: INDIA_CAPABILITIES_FIXTURE,
  us: US_CAPABILITIES_FIXTURE,
  eu: EU_CAPABILITIES_FIXTURE,
  uk: UK_CAPABILITIES_FIXTURE,
  unsupported: UNSUPPORTED_CAPABILITIES_FIXTURE,
} as const

export type CurrencyCode = string
