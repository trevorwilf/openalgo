import { afterEach, describe, expect, it } from 'vitest'
import { makeTab, selectActiveTab, TEMPLATE_CELL_COUNT, useWorkspaceStore } from '../workspaceStore'

describe('workspaceStore', () => {
  afterEach(() => {
    // Reset by hydrating with one empty tab so each test starts fresh.
    const fresh = makeTab('Workspace', '1')
    useWorkspaceStore.getState().hydrate({
      tabs: [fresh],
      activeTabId: fresh.id,
      theme: 'dark',
    })
  })

  it('seeds with one tab whose template is "1" and one cell', () => {
    const tab = selectActiveTab(useWorkspaceStore.getState())
    expect(tab).not.toBeNull()
    expect(tab?.template).toBe('1')
    expect(tab?.cells.length).toBe(1)
    expect(tab?.focusedCellId).toBe(tab?.cells[0].id)
  })

  it('changing template grows or shrinks cells to match TEMPLATE_CELL_COUNT', () => {
    const before = selectActiveTab(useWorkspaceStore.getState())!
    useWorkspaceStore.getState().setTemplate(before.id, '4-quad')
    const after = selectActiveTab(useWorkspaceStore.getState())!
    expect(after.cells.length).toBe(TEMPLATE_CELL_COUNT['4-quad'])
    // Existing cells preserved at the head of the array.
    expect(after.cells[0].id).toBe(before.cells[0].id)
  })

  it('shrinking back drops trailing cells but keeps the first', () => {
    const tab = selectActiveTab(useWorkspaceStore.getState())!
    useWorkspaceStore.getState().setTemplate(tab.id, '6-grid')
    const grown = selectActiveTab(useWorkspaceStore.getState())!
    expect(grown.cells.length).toBe(6)
    useWorkspaceStore.getState().setTemplate(tab.id, '2H')
    const shrunk = selectActiveTab(useWorkspaceStore.getState())!
    expect(shrunk.cells.length).toBe(2)
    expect(shrunk.cells[0].id).toBe(grown.cells[0].id)
  })

  it('addTab appends and switches active', () => {
    const t = makeTab('Crypto', '2V')
    useWorkspaceStore.getState().addTab(t)
    expect(useWorkspaceStore.getState().activeTabId).toBe(t.id)
    expect(useWorkspaceStore.getState().tabs.length).toBe(2)
  })

  it('removeTab keeps a fresh tab if the user closes the last one', () => {
    const before = useWorkspaceStore.getState().tabs[0]
    useWorkspaceStore.getState().removeTab(before.id)
    expect(useWorkspaceStore.getState().tabs.length).toBe(1)
    expect(useWorkspaceStore.getState().tabs[0].id).not.toBe(before.id)
  })

  it('setCellSymbol stores symbol + venue on a specific cell', () => {
    const tab = selectActiveTab(useWorkspaceStore.getState())!
    const cellId = tab.cells[0].id
    useWorkspaceStore.getState().setCellSymbol(tab.id, cellId, 'AAPL', 'XNAS')
    const updated = selectActiveTab(useWorkspaceStore.getState())!
    expect(updated.cells[0].symbol).toBe('AAPL')
    expect(updated.cells[0].venueCode).toBe('XNAS')
  })

  it('setCellEngine swaps the engine without touching symbol', () => {
    const tab = selectActiveTab(useWorkspaceStore.getState())!
    const cellId = tab.cells[0].id
    useWorkspaceStore.getState().setCellSymbol(tab.id, cellId, 'AAPL', 'XNAS')
    useWorkspaceStore.getState().setCellEngine(tab.id, cellId, 'klinechart_pro')
    const updated = selectActiveTab(useWorkspaceStore.getState())!
    expect(updated.cells[0].engine).toBe('klinechart_pro')
    expect(updated.cells[0].symbol).toBe('AAPL')
  })

  it('hydrate replaces full state', () => {
    const t = makeTab('Hydrated', '4-quad')
    useWorkspaceStore.getState().hydrate({
      tabs: [t],
      activeTabId: t.id,
      theme: 'light',
    })
    expect(useWorkspaceStore.getState().tabs.length).toBe(1)
    expect(useWorkspaceStore.getState().theme).toBe('light')
    expect(useWorkspaceStore.getState().hydrated).toBe(true)
  })
})
