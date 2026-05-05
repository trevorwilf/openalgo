import { render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import { OrderOverlayLayer } from '../OrderOverlayLayer'

const ORDERS = [
  {
    order_id: 'o1',
    symbol: 'AAPL',
    side: 'BUY' as const,
    order_type: 'LIMIT',
    qty: '10',
    price: '100',
    status: 'OPEN' as const,
    ts: 1700000000,
  },
  {
    order_id: 'o2',
    symbol: 'AAPL',
    side: 'SELL' as const,
    order_type: 'MARKET',
    qty: '5',
    price: null,
    status: 'PENDING' as const,
    ts: 1700000060,
  },
]

const POSITIONS = [{ symbol: 'AAPL', qty: '15', avg_price: '99.5' }]

const FILLS = [
  {
    fill_id: 'f1',
    order_id: 'o1',
    symbol: 'AAPL',
    side: 'BUY' as const,
    qty: '10',
    price: '100',
    ts: 1700000060,
  },
]

describe('<OrderOverlayLayer>', () => {
  it('renders orders, positions, and fills with the right counts', () => {
    render(<OrderOverlayLayer orders={ORDERS} positions={POSITIONS} fills={FILLS} />)
    const layer = screen.getByTestId('order-overlay-layer')
    expect(layer.getAttribute('data-orders')).toBe('2')
    expect(layer.getAttribute('data-positions')).toBe('1')
    expect(layer.getAttribute('data-fills')).toBe('1')
  })

  it('renders distinct order rows by id', () => {
    render(<OrderOverlayLayer orders={ORDERS} positions={[]} fills={[]} />)
    expect(screen.getByTestId('order-row-o1')).toBeTruthy()
    expect(screen.getByTestId('order-row-o2')).toBeTruthy()
  })

  it('shows MARKET when price is null', () => {
    render(<OrderOverlayLayer orders={ORDERS} positions={[]} fills={[]} />)
    expect(screen.getByTestId('order-row-o2').textContent).toContain('MKT')
  })
})
