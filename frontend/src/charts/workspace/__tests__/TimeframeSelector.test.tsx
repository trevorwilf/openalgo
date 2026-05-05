import { fireEvent, render, screen } from '@testing-library/react'
import { afterEach, describe, expect, it } from 'vitest'
import { makeTab, useWorkspaceStore } from '../../state/workspaceStore'
import type { CanonicalInterval } from '../../types/interval'
import { TimeframeSelector } from '../TimeframeSelector'

afterEach(() => {
  const fresh = makeTab('Workspace', '1')
  useWorkspaceStore.getState().hydrate({
    tabs: [fresh],
    activeTabId: fresh.id,
    theme: 'dark',
  })
})

describe('<TimeframeSelector>', () => {
  it('lists every canonical interval when supportedIntervals=undefined', () => {
    const cell = useWorkspaceStore.getState().tabs[0].cells[0]
    render(<TimeframeSelector cellId={cell.id} />)
    const opts = screen.getAllByRole('option') as HTMLOptionElement[]
    // 17 canonical intervals from D-08.
    expect(opts.length).toBe(17)
  })

  it('filters by broker capability list', () => {
    const cell = useWorkspaceStore.getState().tabs[0].cells[0]
    const supported: CanonicalInterval[] = ['1m', '5m', '1h', '1d']
    render(<TimeframeSelector cellId={cell.id} supportedIntervals={supported} />)
    const opts = screen.getAllByRole('option') as HTMLOptionElement[]
    expect(opts.map((o) => o.value)).toEqual(['1m', '5m', '1h', '1d'])
  })

  it('changing the selection writes back to the store', () => {
    const tab = useWorkspaceStore.getState().tabs[0]
    const cell = tab.cells[0]
    render(<TimeframeSelector cellId={cell.id} supportedIntervals={['1m', '5m', '1h', '1d']} />)
    const select = screen.getByTestId(`timeframe-select-${cell.id}`)
    fireEvent.change(select, { target: { value: '1h' } })
    const after = useWorkspaceStore.getState().tabs[0].cells[0]
    expect(after.timeframe).toBe('1h')
  })

  it('returns null for unknown cell id', () => {
    const { container } = render(<TimeframeSelector cellId="missing" />)
    expect(container.firstChild).toBeNull()
  })
})
