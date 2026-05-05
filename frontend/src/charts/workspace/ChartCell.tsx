// Phase 2 — Workspace Shell
// Per-cell placeholder. Phase 3 wires the engine via the loader.
//
// **No engine module is statically imported here.** The cell only
// holds props + a container ref. Phase 3 hooks the loader (P-02
// boundary). The contract test
// `tests/contracts/test_chart_cell_no_engine_import.test.ts` asserts
// this by source-text inspection.

import { useCallback } from 'react'
import { cn } from '@/lib/utils'
import type { CellConfig } from '../state/workspaceStore'
import { selectActiveTab, useWorkspaceStore } from '../state/workspaceStore'

export interface ChartCellProps {
  cell: CellConfig
  /** True when the cell is the focused cell of the active tab. */
  focused: boolean
  /** Click-to-focus handler — store-backed, supplied by the grid. */
  onFocus(): void
}

export function ChartCell({ cell, focused, onFocus }: ChartCellProps) {
  const handleClick = useCallback(() => {
    onFocus()
  }, [onFocus])

  return (
    // The cell is an interactive container, not a leaf button — Phase 3+
    // adds nested interactive elements (engine selector, symbol overlay).
    // Keep `role="button"` so the focus-shift onClick is announced, but
    // suppress the biome a11y rule that pushes us toward a real <button>
    // (which cannot contain other interactive descendants).
    // biome-ignore lint/a11y/useSemanticElements: see comment above
    <div
      data-testid={`chart-cell-${cell.id}`}
      data-cell-id={cell.id}
      data-focused={focused ? 'true' : 'false'}
      data-engine={cell.engine}
      role="button"
      tabIndex={0}
      onClick={handleClick}
      onKeyDown={(e) => {
        if (e.key === 'Enter' || e.key === ' ') {
          e.preventDefault()
          handleClick()
        }
      }}
      className={cn(
        'relative h-full w-full rounded-sm border bg-card outline-none',
        'flex flex-col items-center justify-center gap-2 p-4',
        'transition-colors',
        focused ? 'ring-2 ring-primary ring-offset-1 ring-offset-background' : 'hover:bg-muted/40'
      )}
    >
      <div className="flex flex-col items-center gap-1 text-sm text-muted-foreground">
        <div className="font-medium text-foreground">{cell.symbol ?? 'No symbol'}</div>
        <div className="text-xs">
          {cell.timeframe} · engine: {cell.engine}
        </div>
      </div>
      <p className="text-xs text-muted-foreground">
        Pick a symbol from the sidebar to render bars (Phase 3).
      </p>
    </div>
  )
}

/**
 * Convenience component used by the grid: looks up the cell's focused
 * state from the active-tab selector and dispatches `focusCell`.
 */
export function ConnectedChartCell({ cell }: { cell: CellConfig }) {
  const activeTab = useWorkspaceStore(selectActiveTab)
  const focusCell = useWorkspaceStore((s) => s.focusCell)
  const focused = activeTab?.focusedCellId === cell.id
  const tabId = activeTab?.id ?? null

  const handleFocus = useCallback(() => {
    if (tabId) focusCell(tabId, cell.id)
  }, [tabId, cell.id, focusCell])

  return <ChartCell cell={cell} focused={focused} onFocus={handleFocus} />
}
