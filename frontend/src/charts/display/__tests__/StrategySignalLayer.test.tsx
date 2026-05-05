import { render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import { StrategySignalLayer } from '../StrategySignalLayer'

describe('<StrategySignalLayer>', () => {
  it('renders signal rows with their kind on data-kind', () => {
    render(
      <StrategySignalLayer
        signals={[
          { id: 1, symbol: 'AAPL', kind: 'BUY', ts: 1700000000, source: 'flow' },
          { id: 2, symbol: 'AAPL', kind: 'EXIT', ts: 1700000060, source: 'python' },
        ]}
      />
    )
    const layer = screen.getByTestId('strategy-signal-layer')
    expect(layer.getAttribute('data-count')).toBe('2')
    expect(screen.getByTestId('signal-row-1').getAttribute('data-kind')).toBe('BUY')
    expect(screen.getByTestId('signal-row-2').getAttribute('data-kind')).toBe('EXIT')
  })

  it('renders nothing when no signals', () => {
    render(<StrategySignalLayer signals={[]} />)
    const layer = screen.getByTestId('strategy-signal-layer')
    expect(layer.getAttribute('data-count')).toBe('0')
  })
})
