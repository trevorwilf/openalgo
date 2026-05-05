// Phase 2 — Workspace Shell
// Per-tab, per-cell zustand store driving the chart workspace.
//
// State separation per HANDOFF P-04: this store is the *display tree*
// state — pure UI selection (active tab, focused cell, layout
// template, theme override). The execution tree (Phase 6) gets its
// own store; the two never share mutable state.
//
// `tabs` is an ordered list — `activeTabId` is the user-selected tab.
// Each tab carries an independent `LayoutTemplate` + per-cell config.
// The first tab + its first cell are seeded from
// `BrokerCapabilities` (no chart-side hardcode — D-10).

import { create } from 'zustand'
import type { CanonicalInterval } from '../types/interval'

export type LayoutTemplate = '1' | '2H' | '2V' | '3-1+2' | '4-quad' | '6-grid'

/** Engine string used by the loader (P-02). */
export type EngineId = 'lightweight' | 'klinechart_pro' | 'tradingview_advanced'

export interface CellConfig {
  /** Stable cell id (not array index) — drawing/indicator rows reference this. */
  id: string
  /** Engine selection per-cell; loader resolves it (Phase 3). */
  engine: EngineId
  /** Active symbol — null until user picks one. */
  symbol: string | null
  /** Venue code (XNAS, XNSE, …). Comes from broker capabilities. */
  venueCode: string | null
  /** Chart timeframe; broker-capability-filtered (Phase 3). */
  timeframe: CanonicalInterval
  /** Optional per-cell theme override. */
  theme?: 'light' | 'dark'
}

export interface TabState {
  id: string
  name: string
  template: LayoutTemplate
  cells: CellConfig[]
  /** Active cell within this tab (null when tab has only one). */
  focusedCellId: string | null
}

interface WorkspaceState {
  tabs: TabState[]
  activeTabId: string | null
  /** Workspace-wide theme; cells may override per-cell. */
  theme: 'light' | 'dark'
  /** Whether the workspace shell has been hydrated from
   *  /api/v2/chart/active-layout (Phase 5). Until true, components
   *  may show a transient placeholder. */
  hydrated: boolean

  // -- actions ---------------------------------------------------------------
  addTab(tab: TabState): void
  removeTab(tabId: string): void
  setActiveTab(tabId: string): void
  renameTab(tabId: string, name: string): void
  setTemplate(tabId: string, template: LayoutTemplate): void
  setCellSymbol(
    tabId: string,
    cellId: string,
    symbol: string | null,
    venueCode?: string | null
  ): void
  setCellTimeframe(tabId: string, cellId: string, timeframe: CanonicalInterval): void
  setCellEngine(tabId: string, cellId: string, engine: EngineId): void
  focusCell(tabId: string, cellId: string | null): void
  setTheme(theme: 'light' | 'dark'): void
  setCellTheme(tabId: string, cellId: string, theme: 'light' | 'dark' | undefined): void
  setHydrated(b: boolean): void
  /** Apply a complete state snapshot — used when restoring from
   *  /api/v2/chart/active-layout (Phase 5 wires this). */
  hydrate(snapshot: {
    tabs: TabState[]
    activeTabId: string | null
    theme?: 'light' | 'dark'
  }): void
}

export const TEMPLATE_CELL_COUNT: Record<LayoutTemplate, number> = {
  '1': 1,
  '2H': 2,
  '2V': 2,
  '3-1+2': 3,
  '4-quad': 4,
  '6-grid': 6,
}

const DEFAULT_TIMEFRAME: CanonicalInterval = '5m'
const DEFAULT_ENGINE: EngineId = 'lightweight'

let _seq = 0
export function nextCellId(): string {
  _seq += 1
  return `cell-${Date.now().toString(36)}-${_seq}`
}

export function nextTabId(): string {
  _seq += 1
  return `tab-${Date.now().toString(36)}-${_seq}`
}

/** Build a fresh tab with N empty cells matching `template`. */
export function makeTab(name: string, template: LayoutTemplate): TabState {
  const id = nextTabId()
  const count = TEMPLATE_CELL_COUNT[template]
  const cells: CellConfig[] = Array.from({ length: count }, () => ({
    id: nextCellId(),
    engine: DEFAULT_ENGINE,
    symbol: null,
    venueCode: null,
    timeframe: DEFAULT_TIMEFRAME,
  }))
  return {
    id,
    name,
    template,
    cells,
    focusedCellId: count > 1 ? null : cells[0].id,
  }
}

/** Resize the cells array of a tab to match the new template's count.
 *  Preserves existing cells (and their state) up to the new count;
 *  appends fresh empty cells when growing. */
function resizeCellsForTemplate(cells: CellConfig[], template: LayoutTemplate): CellConfig[] {
  const target = TEMPLATE_CELL_COUNT[template]
  if (cells.length === target) return cells
  if (cells.length > target) return cells.slice(0, target)
  const extra = Array.from({ length: target - cells.length }, () => ({
    id: nextCellId(),
    engine: DEFAULT_ENGINE,
    symbol: null,
    venueCode: null,
    timeframe: DEFAULT_TIMEFRAME,
  }))
  return [...cells, ...extra]
}

const initialTab = makeTab('Workspace', '1')

export const useWorkspaceStore = create<WorkspaceState>()((set) => ({
  tabs: [initialTab],
  activeTabId: initialTab.id,
  theme: 'dark',
  hydrated: false,

  addTab: (tab) => set((s) => ({ tabs: [...s.tabs, tab], activeTabId: tab.id })),

  removeTab: (tabId) =>
    set((s) => {
      const next = s.tabs.filter((t) => t.id !== tabId)
      if (next.length === 0) {
        const replacement = makeTab('Workspace', '1')
        return { tabs: [replacement], activeTabId: replacement.id }
      }
      const newActive = s.activeTabId === tabId ? next[0].id : s.activeTabId
      return { tabs: next, activeTabId: newActive }
    }),

  setActiveTab: (tabId) =>
    set((s) => (s.tabs.some((t) => t.id === tabId) ? { activeTabId: tabId } : s)),

  renameTab: (tabId, name) =>
    set((s) => ({
      tabs: s.tabs.map((t) => (t.id === tabId ? { ...t, name } : t)),
    })),

  setTemplate: (tabId, template) =>
    set((s) => ({
      tabs: s.tabs.map((t) =>
        t.id === tabId ? { ...t, template, cells: resizeCellsForTemplate(t.cells, template) } : t
      ),
    })),

  setCellSymbol: (tabId, cellId, symbol, venueCode = null) =>
    set((s) => ({
      tabs: s.tabs.map((t) =>
        t.id === tabId
          ? {
              ...t,
              cells: t.cells.map((c) => (c.id === cellId ? { ...c, symbol, venueCode } : c)),
            }
          : t
      ),
    })),

  setCellTimeframe: (tabId, cellId, timeframe) =>
    set((s) => ({
      tabs: s.tabs.map((t) =>
        t.id === tabId
          ? {
              ...t,
              cells: t.cells.map((c) => (c.id === cellId ? { ...c, timeframe } : c)),
            }
          : t
      ),
    })),

  setCellEngine: (tabId, cellId, engine) =>
    set((s) => ({
      tabs: s.tabs.map((t) =>
        t.id === tabId
          ? {
              ...t,
              cells: t.cells.map((c) => (c.id === cellId ? { ...c, engine } : c)),
            }
          : t
      ),
    })),

  focusCell: (tabId, cellId) =>
    set((s) => ({
      tabs: s.tabs.map((t) => (t.id === tabId ? { ...t, focusedCellId: cellId } : t)),
    })),

  setTheme: (theme) => set({ theme }),

  setCellTheme: (tabId, cellId, theme) =>
    set((s) => ({
      tabs: s.tabs.map((t) =>
        t.id === tabId
          ? {
              ...t,
              cells: t.cells.map((c) => (c.id === cellId ? { ...c, theme } : c)),
            }
          : t
      ),
    })),

  setHydrated: (b) => set({ hydrated: b }),

  hydrate: (snapshot) =>
    set({
      tabs: snapshot.tabs.length ? snapshot.tabs : [makeTab('Workspace', '1')],
      activeTabId: snapshot.activeTabId ?? snapshot.tabs[0]?.id ?? null,
      theme: snapshot.theme ?? 'dark',
      hydrated: true,
    }),
}))

/** Selector: active tab object (or null). */
export function selectActiveTab(s: WorkspaceState): TabState | null {
  return s.tabs.find((t) => t.id === s.activeTabId) ?? null
}
