import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'
import { fireEvent, render, screen } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'
import type { CellConfig } from '../../state/workspaceStore'
import { ChartCell } from '../ChartCell'

const baseCell: CellConfig = {
  id: 'cell-1',
  engine: 'lightweight',
  symbol: null,
  venueCode: null,
  timeframe: '5m',
}

describe('<ChartCell>', () => {
  it('renders placeholder UI with engine + timeframe info', () => {
    render(<ChartCell cell={baseCell} focused={false} onFocus={() => undefined} />)
    expect(screen.getByTestId('chart-cell-cell-1')).toBeTruthy()
    expect(screen.getByText('No symbol')).toBeTruthy()
    expect(screen.getByText('5m · engine: lightweight')).toBeTruthy()
  })

  it('calls onFocus on click', () => {
    const onFocus = vi.fn()
    render(<ChartCell cell={baseCell} focused={false} onFocus={onFocus} />)
    fireEvent.click(screen.getByTestId('chart-cell-cell-1'))
    expect(onFocus).toHaveBeenCalledTimes(1)
  })

  it('marks data-focused when focused=true', () => {
    render(<ChartCell cell={baseCell} focused={true} onFocus={() => undefined} />)
    const el = screen.getByTestId('chart-cell-cell-1')
    expect(el.getAttribute('data-focused')).toBe('true')
  })

  it('reflects symbol/timeframe when supplied', () => {
    render(
      <ChartCell
        cell={{ ...baseCell, symbol: 'AAPL', timeframe: '1h' }}
        focused={false}
        onFocus={() => undefined}
      />
    )
    expect(screen.getByText('AAPL')).toBeTruthy()
    expect(screen.getByText('1h · engine: lightweight')).toBeTruthy()
  })
})

// P-02 contract test: ChartCell.tsx must NOT statically import any
// engine adapter. Engine selection happens through the loader at the
// workspace boundary, never inside the cell.
describe('<ChartCell> P-02 boundary', () => {
  const cellSrc = readFileSync(resolve(__dirname, '..', 'ChartCell.tsx'), 'utf-8')

  it.each([
    /from\s+['"]@\/charts\/engine\/lightweight\/[^'"]*['"]/,
    /from\s+['"]@\/charts\/engine\/klinechart\/[^'"]*['"]/,
    /from\s+['"]@\/charts\/engine\/tradingview\/[^'"]*['"]/,
    /from\s+['"]lightweight-charts[^'"]*['"]/,
    /from\s+['"]klinecharts-pro[^'"]*['"]/,
    /from\s+['"]klinecharts[^'"]*['"]/,
  ])('does not import %s', (re) => {
    expect(re.test(cellSrc)).toBe(false)
  })
})
