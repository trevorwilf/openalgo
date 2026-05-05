// Phase 2 — Workspace Shell
// 6-template grid backed by react-resizable-panels.
//
// Templates per HANDOFF Phase 2 §3:
//   '1'      → single cell
//   '2H'     → two horizontal panels (top/bottom)
//   '2V'     → two vertical panels  (left/right)
//   '3-1+2'  → 1 large left, 2 stacked right (1 + (2 stacked))
//   '4-quad' → 2x2 grid
//   '6-grid' → 2x3 grid (2 rows of 3 cells)
//
// The grid wires each Panel to a `CellConfig` from the active tab; cells
// remain stable across resizes because `react-resizable-panels` keys on
// the Panel id (we set it to the cell id).

import type { ReactElement } from 'react'

import { ResizableHandle, ResizablePanel, ResizablePanelGroup } from '@/components/ui/resizable'
import { cn } from '@/lib/utils'
import type { CellConfig, LayoutTemplate, TabState } from '../state/workspaceStore'
import { selectActiveTab, useWorkspaceStore } from '../state/workspaceStore'
import { ConnectedChartCell } from './ChartCell'

interface PanelHostProps {
  cell: CellConfig
  className?: string
}

function PanelHost({ cell, className }: PanelHostProps) {
  return (
    <div data-testid={`grid-panel-${cell.id}`} className={cn('h-full w-full p-1', className)}>
      <ConnectedChartCell cell={cell} />
    </div>
  )
}

function Layout1({ cells }: { cells: CellConfig[] }) {
  return (
    <div data-testid="layout-1" className="h-full w-full">
      <PanelHost cell={cells[0]} />
    </div>
  )
}

function Layout2H({ cells }: { cells: CellConfig[] }) {
  return (
    <div data-testid="layout-2H" className="h-full w-full">
      <ResizablePanelGroup orientation="vertical" className="h-full w-full">
        <ResizablePanel id={cells[0].id} defaultSize={50}>
          <PanelHost cell={cells[0]} />
        </ResizablePanel>
        <ResizableHandle withHandle />
        <ResizablePanel id={cells[1].id} defaultSize={50}>
          <PanelHost cell={cells[1]} />
        </ResizablePanel>
      </ResizablePanelGroup>
    </div>
  )
}

function Layout2V({ cells }: { cells: CellConfig[] }) {
  return (
    <div data-testid="layout-2V" className="h-full w-full">
      <ResizablePanelGroup orientation="horizontal" className="h-full w-full">
        <ResizablePanel id={cells[0].id} defaultSize={50}>
          <PanelHost cell={cells[0]} />
        </ResizablePanel>
        <ResizableHandle withHandle />
        <ResizablePanel id={cells[1].id} defaultSize={50}>
          <PanelHost cell={cells[1]} />
        </ResizablePanel>
      </ResizablePanelGroup>
    </div>
  )
}

function Layout3({ cells }: { cells: CellConfig[] }) {
  return (
    <div data-testid="layout-3-1+2" className="h-full w-full">
      <ResizablePanelGroup orientation="horizontal" className="h-full w-full">
        <ResizablePanel id={cells[0].id} defaultSize={60}>
          <PanelHost cell={cells[0]} />
        </ResizablePanel>
        <ResizableHandle withHandle />
        <ResizablePanel defaultSize={40}>
          <ResizablePanelGroup orientation="vertical">
            <ResizablePanel id={cells[1].id} defaultSize={50}>
              <PanelHost cell={cells[1]} />
            </ResizablePanel>
            <ResizableHandle withHandle />
            <ResizablePanel id={cells[2].id} defaultSize={50}>
              <PanelHost cell={cells[2]} />
            </ResizablePanel>
          </ResizablePanelGroup>
        </ResizablePanel>
      </ResizablePanelGroup>
    </div>
  )
}

function Layout4Quad({ cells }: { cells: CellConfig[] }) {
  return (
    <div data-testid="layout-4-quad" className="h-full w-full">
      <ResizablePanelGroup orientation="vertical" className="h-full w-full">
        <ResizablePanel defaultSize={50}>
          <ResizablePanelGroup orientation="horizontal">
            <ResizablePanel id={cells[0].id} defaultSize={50}>
              <PanelHost cell={cells[0]} />
            </ResizablePanel>
            <ResizableHandle withHandle />
            <ResizablePanel id={cells[1].id} defaultSize={50}>
              <PanelHost cell={cells[1]} />
            </ResizablePanel>
          </ResizablePanelGroup>
        </ResizablePanel>
        <ResizableHandle withHandle />
        <ResizablePanel defaultSize={50}>
          <ResizablePanelGroup orientation="horizontal">
            <ResizablePanel id={cells[2].id} defaultSize={50}>
              <PanelHost cell={cells[2]} />
            </ResizablePanel>
            <ResizableHandle withHandle />
            <ResizablePanel id={cells[3].id} defaultSize={50}>
              <PanelHost cell={cells[3]} />
            </ResizablePanel>
          </ResizablePanelGroup>
        </ResizablePanel>
      </ResizablePanelGroup>
    </div>
  )
}

function Layout6Grid({ cells }: { cells: CellConfig[] }) {
  return (
    <div data-testid="layout-6-grid" className="h-full w-full">
      <ResizablePanelGroup orientation="vertical" className="h-full w-full">
        <ResizablePanel defaultSize={50}>
          <ResizablePanelGroup orientation="horizontal">
            {cells.slice(0, 3).map((c, i) => (
              <PanelGroupRow key={c.id} cell={c} isLast={i === 2} />
            ))}
          </ResizablePanelGroup>
        </ResizablePanel>
        <ResizableHandle withHandle />
        <ResizablePanel defaultSize={50}>
          <ResizablePanelGroup orientation="horizontal">
            {cells.slice(3, 6).map((c, i) => (
              <PanelGroupRow key={c.id} cell={c} isLast={i === 2} />
            ))}
          </ResizablePanelGroup>
        </ResizablePanel>
      </ResizablePanelGroup>
    </div>
  )
}

function PanelGroupRow({
  cell,
  isLast,
}: {
  cell: CellConfig
  isLast: boolean
}) {
  return (
    <>
      <ResizablePanel id={cell.id} defaultSize={33}>
        <PanelHost cell={cell} />
      </ResizablePanel>
      {!isLast && <ResizableHandle withHandle />}
    </>
  )
}

const LAYOUT_RENDERERS: Record<LayoutTemplate, (props: { cells: CellConfig[] }) => ReactElement> = {
  '1': Layout1,
  '2H': Layout2H,
  '2V': Layout2V,
  '3-1+2': Layout3,
  '4-quad': Layout4Quad,
  '6-grid': Layout6Grid,
}

export interface ChartLayoutGridProps {
  /** Override the active tab (used by tests). When omitted, the grid
   *  reads the active tab from the workspace store. */
  tab?: TabState
}

export function ChartLayoutGrid({ tab: tabOverride }: ChartLayoutGridProps = {}) {
  const tabFromStore = useWorkspaceStore(selectActiveTab)
  const tab = tabOverride ?? tabFromStore
  if (!tab) {
    return (
      <div
        data-testid="chart-layout-empty"
        className="flex h-full w-full items-center justify-center text-sm text-muted-foreground"
      >
        No workspace tab selected.
      </div>
    )
  }
  const Renderer = LAYOUT_RENDERERS[tab.template]
  return (
    <div data-testid="chart-layout-grid" className="h-full w-full">
      <Renderer cells={tab.cells} />
    </div>
  )
}

export const LAYOUT_TEMPLATES: ReadonlyArray<{ id: LayoutTemplate; label: string }> = [
  { id: '1', label: 'Single' },
  { id: '2H', label: '2 Horizontal' },
  { id: '2V', label: '2 Vertical' },
  { id: '3-1+2', label: '1 + 2 Stack' },
  { id: '4-quad', label: '4 Quad' },
  { id: '6-grid', label: '6 Grid' },
]
