import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'
import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import type { ChartEngineAdapter } from '../../engine/ChartEngineAdapter'
import type { CellConfig } from '../../state/workspaceStore'
import { makeTab, useWorkspaceStore } from '../../state/workspaceStore'
import { ChartCell } from '../ChartCell'

const baseCell: CellConfig = {
  id: 'cell-1',
  engine: 'lightweight',
  symbol: null,
  venueCode: null,
  timeframe: '5m',
}

function fakeAdapter(): ChartEngineAdapter {
  return {
    engineId: 'lightweight',
    mount: vi.fn(async () => undefined),
    unmount: vi.fn(),
    setBars: vi.fn(),
    appendBar: vi.fn(),
    updateForming: vi.fn(),
    addIndicator: vi.fn(),
    updateIndicator: vi.fn(),
    removeIndicator: vi.fn(),
    addDrawing: vi.fn(),
    removeDrawing: vi.fn(),
    setTheme: vi.fn(),
    resize: vi.fn(),
    onEvent: vi.fn(() => () => undefined),
    serializeState: vi.fn(() => ({
      bars: [],
      panes: [],
      indicators: [],
      drawings: [],
      theme: 'dark',
    })),
    restoreState: vi.fn(),
    getPriceCoordinate: vi.fn(() => 100),
    getTimeCoordinate: vi.fn(() => 200),
  }
}

const fakeFetchBars = vi.fn(async () => ({
  instrument: { instrument_id: null, venue_code: 'XNAS', canonical_symbol: 'AAPL' },
  interval: '5m',
  bars: [],
}))

const fakeLoad = vi.fn(async () => ({
  adapter: fakeAdapter(),
  requested: 'lightweight' as const,
  resolved: 'lightweight' as const,
  fallback: null,
}))

beforeEach(() => {
  fakeFetchBars.mockClear()
  fakeLoad.mockClear()
  // Reset workspace store so the connected hooks don't carry state.
  const fresh = makeTab('Workspace', '1')
  useWorkspaceStore.getState().hydrate({
    tabs: [fresh],
    activeTabId: fresh.id,
    theme: 'dark',
  })
})

afterEach(() => {
  // Allow pending effects to settle.
})

describe('<ChartCell> placeholder rendering (no symbol)', () => {
  it('renders the toolbar + "Pick a symbol" empty state', () => {
    render(
      <ChartCell
        cell={baseCell}
        focused={false}
        onFocus={() => undefined}
        theme="dark"
        fetchBarsImpl={fakeFetchBars}
        loadEngineImpl={fakeLoad}
      />
    )
    expect(screen.getByTestId('chart-cell-cell-1')).toBeTruthy()
    expect(screen.getByTestId('cell-toolbar-cell-1')).toBeTruthy()
    expect(screen.getByText('No symbol')).toBeTruthy()
    expect(screen.getByText(/Pick a symbol from the sidebar/)).toBeTruthy()
  })

  it('does NOT call the loader or bar fetcher when symbol is null', () => {
    render(
      <ChartCell
        cell={baseCell}
        focused={false}
        onFocus={() => undefined}
        theme="dark"
        fetchBarsImpl={fakeFetchBars}
        loadEngineImpl={fakeLoad}
      />
    )
    expect(fakeFetchBars).not.toHaveBeenCalled()
    expect(fakeLoad).not.toHaveBeenCalled()
  })

  it('calls onFocus on click', () => {
    const onFocus = vi.fn()
    render(
      <ChartCell
        cell={baseCell}
        focused={false}
        onFocus={onFocus}
        theme="dark"
        fetchBarsImpl={fakeFetchBars}
        loadEngineImpl={fakeLoad}
      />
    )
    fireEvent.click(screen.getByTestId('chart-cell-cell-1'))
    expect(onFocus).toHaveBeenCalledTimes(1)
  })

  it('marks data-focused="true" when focused', () => {
    render(
      <ChartCell
        cell={baseCell}
        focused
        onFocus={() => undefined}
        theme="dark"
        fetchBarsImpl={fakeFetchBars}
        loadEngineImpl={fakeLoad}
      />
    )
    const el = screen.getByTestId('chart-cell-cell-1')
    expect(el.getAttribute('data-focused')).toBe('true')
  })
})

describe('<ChartCell> with symbol', () => {
  it('mounts the engine and fetches bars when a symbol is set', async () => {
    render(
      <ChartCell
        cell={{ ...baseCell, symbol: 'AAPL', venueCode: 'XNAS' }}
        focused
        onFocus={() => undefined}
        theme="dark"
        fetchBarsImpl={fakeFetchBars}
        loadEngineImpl={fakeLoad}
      />
    )
    await waitFor(() => {
      expect(fakeLoad).toHaveBeenCalled()
      expect(fakeFetchBars).toHaveBeenCalled()
    })
    const args = fakeFetchBars.mock.calls[0][0] as { ref: { canonical_symbol: string } }
    expect(args.ref.canonical_symbol).toBe('AAPL')
  })

  it('reflects symbol + venue in the toolbar', () => {
    render(
      <ChartCell
        cell={{ ...baseCell, symbol: 'AAPL', venueCode: 'XNAS', timeframe: '1h' }}
        focused
        onFocus={() => undefined}
        theme="dark"
        fetchBarsImpl={fakeFetchBars}
        loadEngineImpl={fakeLoad}
      />
    )
    expect(screen.getByText('AAPL')).toBeTruthy()
    expect(screen.getByText('XNAS')).toBeTruthy()
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
    /from\s+['"]\.\.\/engine\/lightweight\/[^'"]*['"]/,
    /from\s+['"]\.\.\/engine\/klinechart\/[^'"]*['"]/,
    /from\s+['"]\.\.\/engine\/tradingview\/[^'"]*['"]/,
    /from\s+['"]lightweight-charts[^'"]*['"]/,
    /from\s+['"]klinecharts-pro[^'"]*['"]/,
    /from\s+['"]klinecharts[^'"]*['"]/,
    /from\s+['"]@klinecharts\/pro[^'"]*['"]/,
  ])('does not import %s', (re) => {
    expect(re.test(cellSrc)).toBe(false)
  })
})
