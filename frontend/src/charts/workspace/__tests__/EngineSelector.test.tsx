import { fireEvent, render, screen } from '@testing-library/react'
import { afterEach, describe, expect, it } from 'vitest'
import { makeTab, useWorkspaceStore } from '../../state/workspaceStore'
import { EngineSelector } from '../EngineSelector'

afterEach(() => {
  const fresh = makeTab('Workspace', '1')
  useWorkspaceStore.getState().hydrate({
    tabs: [fresh],
    activeTabId: fresh.id,
    theme: 'dark',
  })
})

describe('<EngineSelector>', () => {
  it('per-cell variant flips the cell engine without re-mounting the page', () => {
    const tab = useWorkspaceStore.getState().tabs[0]
    const cell = tab.cells[0]
    render(<EngineSelector cellId={cell.id} />)
    const select = screen.getByTestId(`engine-select-${cell.id}`)
    expect(select.getAttribute('data-engine')).toBe('lightweight')
    fireEvent.change(select, { target: { value: 'klinechart_pro' } })
    const after = useWorkspaceStore.getState().tabs[0].cells[0]
    expect(after.engine).toBe('klinechart_pro')
  })

  it('workspace-wide variant applies to every cell of the active tab', () => {
    const t = makeTab('Multi', '4-quad')
    useWorkspaceStore.getState().hydrate({
      tabs: [t],
      activeTabId: t.id,
      theme: 'dark',
    })
    render(<EngineSelector />)
    const select = screen.getByTestId('engine-select-workspace')
    fireEvent.change(select, { target: { value: 'tradingview_advanced' } })
    const after = useWorkspaceStore.getState().tabs[0]
    for (const c of after.cells) {
      expect(c.engine).toBe('tradingview_advanced')
    }
  })

  it('renders all 3 engine choices', () => {
    render(<EngineSelector />)
    const opts = screen.getAllByRole('option')
    const values = opts.map((o) => o.getAttribute('value'))
    expect(values).toEqual(['lightweight', 'klinechart_pro', 'tradingview_advanced'])
  })
})
