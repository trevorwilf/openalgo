import { fireEvent, render, screen } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'
import { OrderEntryHUD, type OrderIntent } from '../OrderEntryHUD'

function setup(overrides: Partial<Parameters<typeof OrderEntryHUD>[0]> = {}) {
  const onIntent = vi.fn(async (_intent: OrderIntent) => undefined)
  const onDismiss = vi.fn()
  render(
    <OrderEntryHUD
      symbol="AAPL"
      liveModeEnabled={false}
      onIntent={onIntent}
      onDismiss={onDismiss}
      generateIdempotencyToken={() => 'tok-test'}
      {...overrides}
    />
  )
  return { onIntent, onDismiss }
}

describe('<OrderEntryHUD> — two-step modal', () => {
  it('starts on the panel step', () => {
    setup()
    expect(screen.getByTestId('hud-proceed')).toBeTruthy()
    expect(screen.queryByTestId('hud-confirm-step')).toBeNull()
  })

  it('paper banner by default (D-04)', () => {
    setup()
    expect(screen.getByTestId('hud-mode-badge').textContent).toBe('PAPER')
  })

  it('live banner when liveModeEnabled', () => {
    setup({ liveModeEnabled: true })
    expect(screen.getByTestId('hud-mode-badge').textContent).toBe('LIVE')
  })

  it('Review proceeds to confirm step (NOT auto-confirm)', () => {
    const { onIntent } = setup()
    fireEvent.change(screen.getByTestId('hud-qty'), { target: { value: '5' } })
    fireEvent.click(screen.getByTestId('hud-proceed'))
    expect(screen.getByTestId('hud-confirm-step')).toBeTruthy()
    expect(onIntent).not.toHaveBeenCalled()
  })

  it('Enter at confirm step does NOT auto-submit (P-10)', () => {
    const { onIntent } = setup()
    fireEvent.change(screen.getByTestId('hud-qty'), { target: { value: '5' } })
    fireEvent.click(screen.getByTestId('hud-proceed'))
    fireEvent.keyDown(screen.getByRole('dialog'), { key: 'Enter' })
    expect(onIntent).not.toHaveBeenCalled()
  })

  it('Confirm click submits the intent with the idempotency token', async () => {
    const { onIntent } = setup()
    fireEvent.change(screen.getByTestId('hud-qty'), { target: { value: '5' } })
    fireEvent.click(screen.getByTestId('hud-proceed'))
    fireEvent.click(screen.getByTestId('hud-confirm'))
    await new Promise((r) => setTimeout(r, 0))
    expect(onIntent).toHaveBeenCalledTimes(1)
    const intent = onIntent.mock.calls[0][0] as OrderIntent
    expect(intent.idempotency_token).toBe('tok-test')
    expect(intent.qty).toBe('5')
  })

  it('ESC dismisses at any step', () => {
    const { onDismiss } = setup()
    fireEvent.keyDown(window, { key: 'Escape' })
    expect(onDismiss).toHaveBeenCalled()
  })

  it('rejects qty <= 0 and stays on the panel step', () => {
    setup()
    fireEvent.change(screen.getByTestId('hud-qty'), { target: { value: '0' } })
    fireEvent.click(screen.getByTestId('hud-proceed'))
    expect(screen.queryByTestId('hud-confirm-step')).toBeNull()
    expect(screen.getByTestId('hud-error')).toBeTruthy()
  })

  it('idempotency token reused across panel→confirm→submit', async () => {
    const { onIntent } = setup()
    fireEvent.change(screen.getByTestId('hud-qty'), { target: { value: '3' } })
    fireEvent.click(screen.getByTestId('hud-proceed'))
    // The token shows in the confirm step.
    expect(screen.getByTestId('hud-confirm-step').textContent).toContain('tok-test')
    fireEvent.click(screen.getByTestId('hud-confirm'))
    await new Promise((r) => setTimeout(r, 0))
    expect(onIntent.mock.calls[0][0].idempotency_token).toBe('tok-test')
  })
})
