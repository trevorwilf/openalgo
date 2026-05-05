import { fireEvent, render, screen } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'
import { OrderCancel } from '../OrderCancel'

function setup(over: Partial<Parameters<typeof OrderCancel>[0]> = {}) {
  const onConfirm = vi.fn(async () => undefined)
  const onDismiss = vi.fn()
  render(
    <OrderCancel
      orderId="o1"
      symbol="AAPL"
      side="BUY"
      qty="10"
      price="100"
      onConfirm={onConfirm}
      onDismiss={onDismiss}
      generateIdempotencyToken={() => 'tok-c'}
      {...over}
    />
  )
  return { onConfirm, onDismiss }
}

describe('<OrderCancel>', () => {
  it('shows order metadata + Confirm button', () => {
    setup()
    const dialog = screen.getByTestId('order-cancel')
    expect(dialog.textContent).toContain('o1')
    expect(dialog.textContent).toContain('AAPL')
    expect(screen.getByTestId('order-cancel-confirm')).toBeTruthy()
  })

  it('Confirm passes the order id + token', async () => {
    const { onConfirm } = setup()
    fireEvent.click(screen.getByTestId('order-cancel-confirm'))
    await new Promise((r) => setTimeout(r, 0))
    expect(onConfirm).toHaveBeenCalledTimes(1)
    expect(onConfirm.mock.calls[0][0]).toEqual({
      order_id: 'o1',
      idempotency_token: 'tok-c',
    })
  })

  it('ESC dismisses', () => {
    const { onDismiss } = setup()
    fireEvent.keyDown(window, { key: 'Escape' })
    expect(onDismiss).toHaveBeenCalled()
  })

  it('Enter does NOT auto-confirm', () => {
    const { onConfirm } = setup()
    fireEvent.keyDown(window, { key: 'Enter' })
    expect(onConfirm).not.toHaveBeenCalled()
  })
})
