import { render, screen, within } from '@testing-library/react'
import { beforeEach, describe, expect, it } from 'vitest'
import { makeTab, useWorkspaceStore } from '../../state/workspaceStore'
import { ChartWorkspace } from '../ChartWorkspace'

beforeEach(() => {
  // Reset to one '1'-template tab so each test starts clean.
  const fresh = makeTab('Workspace', '1')
  useWorkspaceStore.getState().hydrate({
    tabs: [fresh],
    activeTabId: fresh.id,
    theme: 'dark',
  })
})

describe('<ChartWorkspace>', () => {
  it('renders top bar, sidebar, and a single-cell layout by default', () => {
    render(<ChartWorkspace />)
    expect(screen.getByTestId('chart-workspace')).toBeTruthy()
    expect(screen.getByTestId('workspace-topbar')).toBeTruthy()
    expect(screen.getByTestId('workspace-sidebar')).toBeTruthy()
    expect(screen.getByTestId('chart-layout-grid')).toBeTruthy()
    expect(screen.getByTestId('layout-1')).toBeTruthy()
  })

  it('paper banner is visible by default (live_mode_enabled=false / D-04)', () => {
    render(<ChartWorkspace />)
    const banner = screen.getByTestId('paper-live-banner')
    expect(banner.getAttribute('data-mode')).toBe('paper')
    expect(banner.textContent).toContain('PAPER')
  })

  it('live banner replaces paper banner when liveModeEnabled=true', () => {
    render(<ChartWorkspace liveModeEnabled />)
    const banner = screen.getByTestId('paper-live-banner')
    expect(banner.getAttribute('data-mode')).toBe('live')
    expect(banner.textContent).toContain('LIVE')
  })

  it('all 6 layout templates are selectable from sidebar', () => {
    render(<ChartWorkspace />)
    const selector = screen.getByTestId('layout-selector')
    const buttons = within(selector).getAllByRole('button')
    expect(buttons.length).toBe(6)
    const labels = buttons.map((b) => b.textContent)
    expect(labels).toEqual([
      'Single',
      '2 Horizontal',
      '2 Vertical',
      '1 + 2 Stack',
      '4 Quad',
      '6 Grid',
    ])
  })

  it('tab state machine: switching active tab works via top-bar', () => {
    const tabA = useWorkspaceStore.getState().tabs[0]
    const tabB = makeTab('TabB', '2V')
    useWorkspaceStore.getState().addTab(tabB)
    render(<ChartWorkspace />)
    expect(screen.getByTestId(`tab-${tabA.id}`)).toBeTruthy()
    expect(screen.getByTestId(`tab-${tabB.id}`)).toBeTruthy()
    // tabB should be the active one (addTab activates).
    expect(useWorkspaceStore.getState().activeTabId).toBe(tabB.id)
    // Switch back to tabA.
    screen.getByTestId(`tab-${tabA.id}`).click()
    expect(useWorkspaceStore.getState().activeTabId).toBe(tabA.id)
  })

  it('kill switch placeholder renders with default OFF state', () => {
    render(<ChartWorkspace />)
    const ks = screen.getByTestId('kill-switch')
    expect(ks.getAttribute('data-state')).toBe('off')
    expect(ks.textContent).toMatch(/Kill/i)
  })
})
