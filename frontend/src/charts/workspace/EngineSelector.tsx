// Phase 3 — per-cell + workspace engine selector.
//
// Toggling does NOT page-reload. The cell unmounts the active
// adapter, looks up the new engine via the loader, and remounts.
// State (bars, indicators, drawings) round-trips via
// `serializeState` / `restoreState`.

import { type EngineId, selectActiveTab, useWorkspaceStore } from '../state/workspaceStore'

const ENGINE_LABEL: Record<EngineId, string> = {
  lightweight: 'Lightweight',
  klinechart_pro: 'KLineChart Pro',
  tradingview_advanced: 'Advanced (FAC)',
}

const ENGINE_OPTIONS: EngineId[] = ['lightweight', 'klinechart_pro', 'tradingview_advanced']

export interface EngineSelectorProps {
  /** Cell id this selector controls. When omitted, the selector
   *  edits every cell in the active tab (workspace-wide toggle). */
  cellId?: string
  className?: string
}

export function EngineSelector({ cellId, className }: EngineSelectorProps) {
  const activeTab = useWorkspaceStore(selectActiveTab)
  const setCellEngine = useWorkspaceStore((s) => s.setCellEngine)

  if (!activeTab) return null

  const cell = cellId ? activeTab.cells.find((c) => c.id === cellId) : null
  // Workspace-wide selector reflects the focused cell's engine.
  const focused = activeTab.focusedCellId
    ? activeTab.cells.find((c) => c.id === activeTab.focusedCellId)
    : null
  const current = cell?.engine ?? focused?.engine ?? activeTab.cells[0]?.engine ?? 'lightweight'

  const handleChange = (next: EngineId) => {
    if (cellId) {
      setCellEngine(activeTab.id, cellId, next)
      return
    }
    // Workspace-wide: apply to every cell in the active tab.
    for (const c of activeTab.cells) {
      setCellEngine(activeTab.id, c.id, next)
    }
  }

  return (
    <select
      data-testid={cellId ? `engine-select-${cellId}` : 'engine-select-workspace'}
      data-engine={current}
      value={current}
      onChange={(e) => handleChange(e.target.value as EngineId)}
      className={className ?? 'rounded-sm border bg-background px-2 py-1 text-xs'}
      aria-label="Chart engine"
    >
      {ENGINE_OPTIONS.map((id) => (
        <option key={id} value={id}>
          {ENGINE_LABEL[id]}
        </option>
      ))}
    </select>
  )
}
