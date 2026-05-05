// Phase 3 — engine-mounted chart cell.
//
// Phase 2 shipped a click-to-focus placeholder. Phase 3 layers the
// historical bar fetcher + engine adapter on top: when the cell has a
// symbol, the cell calls the engine loader (loader-only — P-02 holds),
// fetches bars from /api/v2/bars, and feeds them to the adapter.
//
// **No engine module is statically imported here.** The cell only
// references `loader.ts` and `ChartEngineAdapter` types. The contract
// test in ChartCell.test.tsx asserts this by source-text inspection.

import { useCallback, useEffect, useRef, useState } from 'react'
import { cn } from '@/lib/utils'
import { getBars } from '../datafeed/historical'
import type { ChartEngineAdapter } from '../engine/ChartEngineAdapter'
import { type LoadEngineResult, loadEngine } from '../engine/loader'
import type { CellConfig } from '../state/workspaceStore'
import { selectActiveTab, useWorkspaceStore } from '../state/workspaceStore'
import { EngineSelector } from './EngineSelector'
import { TimeframeSelector } from './TimeframeSelector'

export interface ChartCellProps {
  cell: CellConfig
  /** True when the cell is the focused cell of the active tab. */
  focused: boolean
  /** Click-to-focus handler — store-backed, supplied by the grid. */
  onFocus(): void
  /** Workspace-wide theme; the cell's `theme` override wins when set. */
  theme: 'light' | 'dark'
  /** Test seam — overrides `getBars` for hermetic tests. */
  fetchBarsImpl?: typeof getBars
  /** Test seam — overrides `loadEngine` for hermetic tests. */
  loadEngineImpl?: (engineId: CellConfig['engine']) => Promise<LoadEngineResult>
}

interface MountedState {
  adapter: ChartEngineAdapter
  /** What the loader actually mounted; may differ from request. */
  resolved: CellConfig['engine']
}

/** Lookback window for the initial bar load. Phase 4 streams updates
 *  forward; Phase 3 only paints the historical tail. */
const INITIAL_LOOKBACK_BY_INTERVAL: Record<CellConfig['timeframe'], number> = {
  '1s': 60 * 30,
  '5s': 60 * 60 * 2,
  '15s': 60 * 60 * 4,
  '30s': 60 * 60 * 8,
  '1m': 60 * 60 * 24,
  '2m': 60 * 60 * 24 * 2,
  '3m': 60 * 60 * 24 * 3,
  '5m': 60 * 60 * 24 * 5,
  '10m': 60 * 60 * 24 * 10,
  '15m': 60 * 60 * 24 * 15,
  '30m': 60 * 60 * 24 * 30,
  '1h': 60 * 60 * 24 * 60,
  '2h': 60 * 60 * 24 * 90,
  '4h': 60 * 60 * 24 * 180,
  '1d': 60 * 60 * 24 * 365 * 3,
  '1w': 60 * 60 * 24 * 365 * 10,
  '1mo': 60 * 60 * 24 * 365 * 25,
}

export function ChartCell({
  cell,
  focused,
  onFocus,
  theme,
  fetchBarsImpl,
  loadEngineImpl,
}: ChartCellProps) {
  const containerRef = useRef<HTMLDivElement | null>(null)
  const mountedRef = useRef<MountedState | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [loading, setLoading] = useState(false)
  const [bars, setBars] = useState<number>(0)
  const [resolvedEngine, setResolvedEngine] = useState<CellConfig['engine']>(cell.engine)

  const handleClick = useCallback(() => {
    onFocus()
  }, [onFocus])

  // Apply the per-cell theme override to the workspace theme.
  const activeTheme = cell.theme ?? theme

  // Mount/unmount + engine-swap effect. Splitting the mount and the
  // bar fetch keeps swapping engines O(1) without an extra round-trip
  // to /api/v2/bars.
  useEffect(() => {
    let cancelled = false
    if (!containerRef.current || !cell.symbol) return undefined
    const container = containerRef.current

    const load = loadEngineImpl ?? loadEngine

    setError(null)
    setLoading(true)
    load(cell.engine)
      .then(async (result) => {
        if (cancelled) return
        // Tear down a previous adapter (engine swap path).
        const prev = mountedRef.current
        if (prev) {
          const state = prev.adapter.serializeState()
          prev.adapter.unmount()
          mountedRef.current = null
          // Mount fresh adapter, restore state.
          const rect = container.getBoundingClientRect()
          await result.adapter.mount({
            container,
            theme: activeTheme,
            width: rect.width || 600,
            height: rect.height || 400,
          })
          result.adapter.restoreState(state)
        } else {
          const rect = container.getBoundingClientRect()
          await result.adapter.mount({
            container,
            theme: activeTheme,
            width: rect.width || 600,
            height: rect.height || 400,
          })
        }
        mountedRef.current = { adapter: result.adapter, resolved: result.resolved }
        setResolvedEngine(result.resolved)
      })
      .catch((err) => {
        if (cancelled) return
        setError(err instanceof Error ? err.message : String(err))
      })
      .finally(() => {
        if (!cancelled) setLoading(false)
      })

    return () => {
      cancelled = true
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [cell.engine, cell.symbol])

  // Bar fetch effect — re-runs when symbol or timeframe changes.
  useEffect(() => {
    let cancelled = false
    if (!cell.symbol) return undefined
    const fetchImpl = fetchBarsImpl ?? getBars

    const lookback = INITIAL_LOOKBACK_BY_INTERVAL[cell.timeframe]
    const now = Math.trunc(Date.now() / 1000)
    setLoading(true)
    fetchImpl({
      ref: { canonical_symbol: cell.symbol, venue_code: cell.venueCode ?? undefined },
      interval: cell.timeframe,
      from: now - lookback,
      to: now,
    })
      .then((res) => {
        if (cancelled) return
        const adapter = mountedRef.current?.adapter
        if (adapter) adapter.setBars(res.bars)
        setBars(res.bars.length)
      })
      .catch((err) => {
        if (cancelled) return
        setError(err instanceof Error ? err.message : String(err))
      })
      .finally(() => {
        if (!cancelled) setLoading(false)
      })

    return () => {
      cancelled = true
    }
  }, [cell.symbol, cell.timeframe, cell.venueCode, fetchBarsImpl])

  // Theme propagation.
  useEffect(() => {
    const adapter = mountedRef.current?.adapter
    if (adapter) adapter.setTheme(activeTheme)
  }, [activeTheme])

  // Adapter teardown on unmount.
  useEffect(() => {
    return () => {
      const adapter = mountedRef.current?.adapter
      if (adapter) adapter.unmount()
      mountedRef.current = null
    }
  }, [])

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
      data-engine-resolved={resolvedEngine}
      data-bars={bars}
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
        'flex flex-col gap-2 overflow-hidden p-1',
        'transition-colors',
        focused ? 'ring-2 ring-primary ring-offset-1 ring-offset-background' : 'hover:bg-muted/40'
      )}
    >
      <div
        className="flex items-center gap-2 px-1 text-xs text-muted-foreground"
        data-testid={`cell-toolbar-${cell.id}`}
      >
        <span className="font-medium text-foreground">
          {cell.symbol ?? 'No symbol'}
          {cell.venueCode ? <span className="ml-1 opacity-60">{cell.venueCode}</span> : null}
        </span>
        <TimeframeSelector
          cellId={cell.id}
          className="ml-auto rounded-sm border bg-background px-2 py-0.5 text-xs"
        />
        <EngineSelector
          cellId={cell.id}
          className="rounded-sm border bg-background px-2 py-0.5 text-xs"
        />
      </div>
      <div
        ref={containerRef}
        data-testid={`engine-host-${cell.id}`}
        className="relative flex-1 overflow-hidden rounded-sm bg-card"
      >
        {!cell.symbol && (
          <div className="flex h-full w-full items-center justify-center text-xs text-muted-foreground">
            Pick a symbol from the sidebar to render bars.
          </div>
        )}
        {error && (
          <div
            data-testid={`cell-error-${cell.id}`}
            className="absolute inset-x-0 top-0 m-1 rounded-sm bg-destructive/10 px-2 py-1 text-xs text-destructive"
          >
            {error}
          </div>
        )}
        {loading && (
          <div
            data-testid={`cell-loading-${cell.id}`}
            className="absolute inset-x-0 bottom-0 m-1 rounded-sm bg-muted/40 px-2 py-0.5 text-[10px] text-muted-foreground"
          >
            Loading…
          </div>
        )}
      </div>
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
  const theme = useWorkspaceStore((s) => s.theme)
  const focused = activeTab?.focusedCellId === cell.id
  const tabId = activeTab?.id ?? null

  const handleFocus = useCallback(() => {
    if (tabId) focusCell(tabId, cell.id)
  }, [tabId, cell.id, focusCell])

  return <ChartCell cell={cell} focused={focused} onFocus={handleFocus} theme={theme} />
}
