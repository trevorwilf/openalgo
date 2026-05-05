// Phase 2 — Workspace Shell
// Symbol search + watchlist placeholder + layout selector.
//
// Symbol search wires through the engine-independent
// `frontend/src/charts/datafeed/symbols.ts` wrapper (which calls
// `/search/api/search`). Phase 3 wires watchlist persistence end-to-
// end via /api/v2/chart/watchlists; Phase 2 ships a local placeholder.

import { Search } from 'lucide-react'
import { type FormEvent, useCallback, useState } from 'react'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { cn } from '@/lib/utils'
import { type SymbolMatch, searchSymbols } from '../datafeed/symbols'
import { selectActiveTab, useWorkspaceStore } from '../state/workspaceStore'
import { LAYOUT_TEMPLATES } from './ChartLayoutGrid'

export interface WorkspaceSidebarProps {
  /** Override the symbol search impl (used by tests). */
  searchImpl?: typeof searchSymbols
}

export function WorkspaceSidebar({ searchImpl }: WorkspaceSidebarProps = {}) {
  const [query, setQuery] = useState('')
  const [results, setResults] = useState<SymbolMatch[]>([])
  const [searching, setSearching] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const search = searchImpl ?? searchSymbols

  const activeTab = useWorkspaceStore(selectActiveTab)
  const setTemplate = useWorkspaceStore((s) => s.setTemplate)
  const setCellSymbol = useWorkspaceStore((s) => s.setCellSymbol)

  const targetCellId = activeTab?.focusedCellId ?? activeTab?.cells[0]?.id ?? null

  const handleSearch = useCallback(
    async (e: FormEvent) => {
      e.preventDefault()
      setError(null)
      const q = query.trim()
      if (!q) {
        setResults([])
        return
      }
      setSearching(true)
      try {
        const matches = await search({ query: q, limit: 25 })
        setResults(matches)
      } catch (err) {
        setError(err instanceof Error ? err.message : String(err))
      } finally {
        setSearching(false)
      }
    },
    [query, search]
  )

  const handlePick = useCallback(
    (m: SymbolMatch) => {
      if (!activeTab || !targetCellId) return
      setCellSymbol(activeTab.id, targetCellId, m.symbol, m.exchange)
    },
    [activeTab, targetCellId, setCellSymbol]
  )

  return (
    <aside
      data-testid="workspace-sidebar"
      className="flex h-full w-full flex-col gap-4 border-r bg-card/40 p-3 text-sm"
    >
      <section>
        <header className="mb-1 px-1 text-xs font-medium uppercase tracking-wide text-muted-foreground">
          Symbol search
        </header>
        <form onSubmit={handleSearch} className="flex items-center gap-1">
          <div className="relative flex-1">
            <Search className="pointer-events-none absolute left-2 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground" />
            <Input
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              placeholder="AAPL, RELIANCE, BTC/USD…"
              className="pl-7"
              aria-label="Symbol search"
            />
          </div>
          <Button type="submit" size="sm" disabled={searching}>
            {searching ? '…' : 'Find'}
          </Button>
        </form>
        {error && (
          <p data-testid="symbol-search-error" className="mt-1 text-xs text-destructive">
            {error}
          </p>
        )}
        <ul className="mt-2 max-h-72 overflow-y-auto" data-testid="symbol-results">
          {results.map((r) => (
            <li key={`${r.exchange}:${r.symbol}`}>
              <button
                type="button"
                onClick={() => handlePick(r)}
                className={cn(
                  'flex w-full flex-col rounded-sm px-2 py-1 text-left',
                  'hover:bg-muted/40'
                )}
              >
                <span className="text-sm font-medium">{r.symbol}</span>
                <span className="text-xs text-muted-foreground">
                  {r.exchange}
                  {r.name ? ` · ${r.name}` : ''}
                </span>
              </button>
            </li>
          ))}
          {!searching && results.length === 0 && query.trim() !== '' && !error && (
            <li
              className="px-2 py-1 text-xs text-muted-foreground"
              data-testid="symbol-results-empty"
            >
              No matches.
            </li>
          )}
        </ul>
      </section>

      <section>
        <header className="mb-1 px-1 text-xs font-medium uppercase tracking-wide text-muted-foreground">
          Watchlist
        </header>
        <p
          data-testid="watchlist-placeholder"
          className="rounded-sm border border-dashed p-3 text-xs text-muted-foreground"
        >
          Watchlists wire end-to-end in Phase 3 (uses
          <code className="mx-1">/api/v2/chart/watchlists</code>).
        </p>
      </section>

      <section>
        <header className="mb-1 px-1 text-xs font-medium uppercase tracking-wide text-muted-foreground">
          Layout
        </header>
        <div className="grid grid-cols-3 gap-1" data-testid="layout-selector">
          {LAYOUT_TEMPLATES.map((t) => (
            <button
              key={t.id}
              type="button"
              onClick={() => activeTab && setTemplate(activeTab.id, t.id)}
              data-active={activeTab?.template === t.id ? 'true' : 'false'}
              className={cn(
                'rounded-sm border px-2 py-1 text-xs',
                'hover:bg-muted/40',
                activeTab?.template === t.id
                  ? 'border-primary text-primary'
                  : 'text-muted-foreground'
              )}
            >
              {t.label}
            </button>
          ))}
        </div>
      </section>
    </aside>
  )
}
