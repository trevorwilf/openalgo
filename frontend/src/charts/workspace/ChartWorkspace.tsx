// Phase 2 — Workspace Shell
// Top-level shell for /charts. Composes top bar, sidebar, and the
// layout grid. No engine wired yet — that's Phase 3. The shell is
// region-agnostic (NOT under <IndiaOnly>) and visible to every
// authenticated broker session.

import { ResizableHandle, ResizablePanel, ResizablePanelGroup } from '@/components/ui/resizable'
import { ChartLayoutGrid } from './ChartLayoutGrid'
import { WorkspaceSidebar } from './WorkspaceSidebar'
import { WorkspaceTopBar } from './WorkspaceTopBar'

export interface ChartWorkspaceProps {
  /** Test seam — flips the paper/live banner to live. */
  liveModeEnabled?: boolean
}

export function ChartWorkspace({ liveModeEnabled }: ChartWorkspaceProps = {}) {
  return (
    <div
      data-testid="chart-workspace"
      className="flex h-full w-full flex-col overflow-hidden bg-background"
    >
      <WorkspaceTopBar liveModeEnabled={liveModeEnabled} />
      <ResizablePanelGroup orientation="horizontal" className="flex-1">
        <ResizablePanel id="sidebar" defaultSize={20} minSize={12}>
          <WorkspaceSidebar />
        </ResizablePanel>
        <ResizableHandle withHandle />
        <ResizablePanel id="grid" defaultSize={80}>
          <ChartLayoutGrid />
        </ResizablePanel>
      </ResizablePanelGroup>
    </div>
  )
}

export default ChartWorkspace
