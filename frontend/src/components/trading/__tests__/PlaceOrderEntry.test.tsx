import { render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import { PlaceOrderEntry } from '../PlaceOrderEntry'
import type { BrokerCapabilities } from '@/types/capabilities'

const usCaps: BrokerCapabilities = {
  broker_name: 'alpaca',
  broker_type: 'US_stock',
  supported_exchanges: ['XNAS'],
  leverage_config: false,
  broker_code: 'alpaca',
  broker_display_name: 'Alpaca',
  market_families: ['US_STOCK'],
  supported_regions: ['us'],
  supported_venue_codes: ['XNAS'],
  supported_asset_classes: ['EQUITY'],
  supported_order_types: ['MARKET', 'LIMIT'],
  supported_time_in_force: ['DAY', 'GTC'],
  supported_sessions: ['REGULAR'],
  supported_quantity_units: ['WHOLE', 'FRACTIONAL', 'NOTIONAL'],
  trading_currencies: ['USD'],
  base_currency: 'USD',
  supports_fractional: true,
  supports_notional_orders: true,
  supports_extended_hours: false,
  supports_short_selling: true,
  supports_analyzer: true,
  features: {},
}

const inCaps: BrokerCapabilities = {
  ...usCaps,
  broker_name: 'zerodha',
  broker_type: 'IN_stock',
  broker_code: 'zerodha',
  market_families: ['IN_STOCK'],
  supported_regions: ['india'],
  supported_venue_codes: ['NSE', 'BSE'],
  supported_quantity_units: ['WHOLE', 'LOTS'],
  supports_fractional: false,
  supports_notional_orders: false,
  trading_currencies: ['INR'],
  base_currency: 'INR',
}

const usInstrument = {
  venue_code: 'XNAS',
  canonical_symbol: 'AAPL',
  asset_class: 'EQUITY' as const,
  currency: 'USD',
  supports_fractional: true,
}

describe('PlaceOrderEntry dispatch', () => {
  it('renders V2 ticket for non-Indian brokers', () => {
    render(
      <PlaceOrderEntry
        apikey="x"
        capabilities={usCaps}
        rules={[]}
        instrument={usInstrument}
      />,
    )
    expect(screen.getByTestId('place-order-v2')).toBeInTheDocument()
  })

  it('renders legacy dispatcher for Indian brokers', () => {
    function Legacy({ apikey }: { apikey: string }) {
      return <div data-testid="legacy-dialog">legacy {apikey}</div>
    }
    render(
      <PlaceOrderEntry
        apikey="x"
        capabilities={inCaps}
        rules={[]}
        instrument={usInstrument}
        LegacyDialog={Legacy}
      />,
    )
    expect(screen.getByTestId('legacy-dialog')).toBeInTheDocument()
    expect(screen.queryByTestId('place-order-v2')).toBeNull()
  })

  it('shows a loading state when capabilities have not loaded', () => {
    render(
      <PlaceOrderEntry
        apikey="x"
        capabilities={null}
        rules={[]}
        instrument={usInstrument}
      />,
    )
    expect(screen.getByTestId('v2-entry-loading')).toBeInTheDocument()
  })

  it('shows a placeholder for Indian brokers when no LegacyDialog is wired in', () => {
    render(
      <PlaceOrderEntry
        apikey="x"
        capabilities={inCaps}
        rules={[]}
        instrument={usInstrument}
      />,
    )
    expect(screen.getByTestId('v2-entry-legacy-placeholder')).toBeInTheDocument()
  })
})
