import { render, screen, fireEvent, waitFor } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { PlaceOrderDialogV2, type Instrument } from '../PlaceOrderDialogV2'
import type { BrokerCapabilities } from '@/types/capabilities'
import type { BrokerOrderRule } from '@/types/broker-rules'

const alpacaCaps: BrokerCapabilities = {
  broker_name: 'alpaca',
  broker_type: 'US_stock',
  supported_exchanges: ['XNAS', 'XNYS', 'ARCX', 'BATS'],
  leverage_config: false,
  broker_code: 'alpaca',
  broker_display_name: 'Alpaca',
  market_families: ['US_STOCK'],
  supported_regions: ['us'],
  supported_venue_codes: ['XNAS', 'XNYS', 'ARCX', 'BATS'],
  supported_asset_classes: ['EQUITY', 'ETF'],
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

const alpacaRule: BrokerOrderRule = {
  venue_code: null,
  asset_class: 'EQUITY',
  session: 'REGULAR',
  side: null,
  quantity_unit: null,
  allowed_order_types: ['MARKET', 'LIMIT'],
  allowed_time_in_force: ['DAY', 'GTC'],
  allows_fractional: true,
  allows_notional: true,
  allows_short: true,
  requires_limit_price: false,
}

const aaplInstrument: Instrument = {
  instrument_id: '00000000-0000-0000-0000-000000000001',
  venue_code: 'XNAS',
  canonical_symbol: 'AAPL',
  asset_class: 'EQUITY',
  currency: 'USD',
  tick_size: '0.01',
  supports_fractional: true,
}

describe('PlaceOrderDialogV2 — Alpaca / XNAS / AAPL', () => {
  beforeEach(() => {
    vi.restoreAllMocks()
  })

  it('renders WHOLE, FRACTIONAL, NOTIONAL quantity units', () => {
    render(
      <PlaceOrderDialogV2
        apikey="x"
        capabilities={alpacaCaps}
        rules={[alpacaRule]}
        instrument={aaplInstrument}
      />,
    )
    const qu = screen.getByTestId('v2-quantity-unit') as HTMLSelectElement
    const values = Array.from(qu.options).map((o) => o.value)
    expect(values).toEqual(['WHOLE', 'FRACTIONAL', 'NOTIONAL'])
  })

  it('renders DAY and GTC time-in-force', () => {
    render(
      <PlaceOrderDialogV2
        apikey="x"
        capabilities={alpacaCaps}
        rules={[alpacaRule]}
        instrument={aaplInstrument}
      />,
    )
    const tif = screen.getByTestId('v2-tif') as HTMLSelectElement
    const values = Array.from(tif.options).map((o) => o.value)
    expect(values).toEqual(['DAY', 'GTC'])
  })

  it('renders MARKET and LIMIT order types', () => {
    render(
      <PlaceOrderDialogV2
        apikey="x"
        capabilities={alpacaCaps}
        rules={[alpacaRule]}
        instrument={aaplInstrument}
      />,
    )
    const ot = screen.getByTestId('v2-order-type') as HTMLSelectElement
    const values = Array.from(ot.options).map((o) => o.value)
    expect(values).toEqual(['MARKET', 'LIMIT'])
  })

  it('does NOT render the extended-hours toggle when supports_extended_hours is false', () => {
    render(
      <PlaceOrderDialogV2
        apikey="x"
        capabilities={alpacaCaps}
        rules={[alpacaRule]}
        instrument={aaplInstrument}
      />,
    )
    expect(screen.queryByTestId('v2-extended-hours')).toBeNull()
  })

  it('renders the extended-hours toggle when supports_extended_hours is true', () => {
    render(
      <PlaceOrderDialogV2
        apikey="x"
        capabilities={{ ...alpacaCaps, supports_extended_hours: true }}
        rules={[alpacaRule]}
        instrument={aaplInstrument}
      />,
    )
    expect(screen.getByTestId('v2-extended-hours')).toBeInTheDocument()
  })

  it('does NOT render the product-type selector (Indian legacy concept)', () => {
    render(
      <PlaceOrderDialogV2
        apikey="x"
        capabilities={alpacaCaps}
        rules={[alpacaRule]}
        instrument={aaplInstrument}
      />,
    )
    expect(screen.queryByTestId('v2-product-type-present')).toBeNull()
  })

  it('formats NOTIONAL quantity with USD currency', async () => {
    render(
      <PlaceOrderDialogV2
        apikey="x"
        capabilities={alpacaCaps}
        rules={[alpacaRule]}
        instrument={aaplInstrument}
      />,
    )
    const qu = screen.getByTestId('v2-quantity-unit')
    fireEvent.change(qu, { target: { value: 'NOTIONAL' } })
    const qty = screen.getByTestId('v2-quantity')
    fireEvent.change(qty, { target: { value: '100' } })
    const formatted = screen.getByTestId('v2-quantity-formatted')
    expect(formatted.textContent).toMatch(/\$/)
    expect(formatted.textContent).toMatch(/100/)
  })

  it('submits to /api/v2/orders with normalized body', async () => {
    const fetchMock = vi
      .spyOn(global, 'fetch')
      .mockResolvedValue(
        new Response(JSON.stringify({ data: { order_id: 'o-1', status: 'new' } }), {
          status: 200,
          headers: { 'Content-Type': 'application/json' },
        }),
      )

    const onSubmit = vi.fn()
    render(
      <PlaceOrderDialogV2
        apikey="KEY-42"
        capabilities={alpacaCaps}
        rules={[alpacaRule]}
        instrument={aaplInstrument}
        onSubmit={onSubmit}
      />,
    )
    fireEvent.click(screen.getByTestId('v2-submit'))
    await waitFor(() => expect(onSubmit).toHaveBeenCalled())

    const [url, init] = fetchMock.mock.calls[0]
    expect(url).toBe('/api/v2/orders')
    const body = JSON.parse((init as RequestInit).body as string)
    expect(body.apikey).toBe('KEY-42')
    expect(body.instrument.canonical_symbol).toBe('AAPL')
    expect(body.side).toBe('BUY')
    expect(body.order_type).toBe('MARKET')
    expect(body.quantity_unit).toBe('WHOLE')
    expect(body.time_in_force).toBe('DAY')
  })
})

describe('PlaceOrderDialogV2 — capability gates', () => {
  it('hides FRACTIONAL when capabilities.supports_fractional is false', () => {
    render(
      <PlaceOrderDialogV2
        apikey="x"
        capabilities={{ ...alpacaCaps, supports_fractional: false }}
        rules={[alpacaRule]}
        instrument={aaplInstrument}
      />,
    )
    const qu = screen.getByTestId('v2-quantity-unit') as HTMLSelectElement
    const values = Array.from(qu.options).map((o) => o.value)
    expect(values).not.toContain('FRACTIONAL')
  })

  it('hides NOTIONAL when rule.allows_notional is false', () => {
    render(
      <PlaceOrderDialogV2
        apikey="x"
        capabilities={alpacaCaps}
        rules={[{ ...alpacaRule, allows_notional: false }]}
        instrument={aaplInstrument}
      />,
    )
    const qu = screen.getByTestId('v2-quantity-unit') as HTMLSelectElement
    const values = Array.from(qu.options).map((o) => o.value)
    expect(values).not.toContain('NOTIONAL')
  })
})
