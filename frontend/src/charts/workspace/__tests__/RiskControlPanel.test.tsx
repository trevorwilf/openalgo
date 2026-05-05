import { fireEvent, render, screen } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'
import { RiskControlPanel, type RiskControlState } from '../RiskControlPanel'

function defaults(over: Partial<RiskControlState> = {}): RiskControlState {
  return {
    killSwitch: false,
    liveModeEnabled: false,
    modifyConfirmEnabled: false,
    maxOrderSize: 100,
    maxNotional: '100000',
    currency: 'USD',
    ...over,
  }
}

describe('<RiskControlPanel>', () => {
  it('renders default state with kill OFF + live OFF + modifyConfirm OFF', () => {
    render(<RiskControlPanel state={defaults()} onChange={() => undefined} />)
    expect(screen.getByTestId('risk-kill-toggle').getAttribute('data-state')).toBe('off')
    expect(screen.getByTestId('risk-modify-confirm-toggle').getAttribute('data-state')).toBe('off')
    expect(screen.getByTestId('risk-live-open-gate')).toBeTruthy()
  })

  it('toggling kill-switch ON resets live-mode to false', () => {
    const onChange = vi.fn()
    render(<RiskControlPanel state={defaults({ liveModeEnabled: true })} onChange={onChange} />)
    fireEvent.click(screen.getByTestId('risk-kill-toggle'))
    expect(onChange).toHaveBeenCalledWith(
      expect.objectContaining({ killSwitch: true, liveModeEnabled: false })
    )
  })

  it('live-mode gate requires all 3 acks before Confirm enables', () => {
    const onChange = vi.fn()
    render(<RiskControlPanel state={defaults()} onChange={onChange} />)
    fireEvent.click(screen.getByTestId('risk-live-open-gate'))
    expect(screen.getByTestId('live-mode-gate')).toBeTruthy()
    const confirm = screen.getByTestId('live-gate-confirm')
    expect(confirm).toBeDisabled()

    fireEvent.click(screen.getByTestId('live-ack-1'))
    expect(confirm).toBeDisabled()
    fireEvent.click(screen.getByTestId('live-ack-2'))
    expect(confirm).toBeDisabled()
    fireEvent.click(screen.getByTestId('live-ack-3'))
    expect(confirm).not.toBeDisabled()

    fireEvent.click(confirm)
    expect(onChange).toHaveBeenCalledWith(expect.objectContaining({ liveModeEnabled: true }))
  })

  it('modify-confirm toggle defaults OFF and flips on click', () => {
    const onChange = vi.fn()
    render(<RiskControlPanel state={defaults()} onChange={onChange} />)
    fireEvent.click(screen.getByTestId('risk-modify-confirm-toggle'))
    expect(onChange).toHaveBeenCalledWith(expect.objectContaining({ modifyConfirmEnabled: true }))
  })
})
