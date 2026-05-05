// Phase 2 + Phase 3 — sidebar with symbol search, watchlist (DB-backed),
// and layout selector.
//
// Symbol search wires through the engine-independent
// `frontend/src/charts/datafeed/symbols.ts` wrapper (which calls
// `/search/api/search`). The watchlist round-trips to
// `/api/v2/chart/watchlists`; Phase 3 wires only this endpoint
// end-to-end (the rest of the chart CRUD is Phase 5).

import { Plus, Search, Star, Trash2 } from 'lucide-react'
import { type FormEvent, useCallback, useEffect, useState } from 'react'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { cn } from '@/lib/utils'
import { type SymbolMatch, searchSymbols } from '../datafeed/symbols'
import {
  deleteWatchlist as deleteWatchlistApi,
  listWatchlists as listWatchlistsApi,
  saveWatchlist as saveWatchlistApi,
  type WatchlistRow,
} from '../persistence/watchlists'
import { selectActiveTab, useWorkspaceStore } from '../state/workspaceStore'
import { LAYOUT_TEMPLATES } from './ChartLayoutGrid'

export interface WorkspaceSidebarProps {
  /** Override the symbol search impl (used by tests). */
  searchImpl?: typeof searchSymbols
  /** Override the watchlist endpoints (used by tests to skip auth). */
  watchlistImpls?: {
    list?: typeof listWatchlistsApi
    save?: typeof saveWatchlistApi
    remove?: typeof deleteWatchlistApi
  }
  /** Override the apikey supplier (used by tests). */
  getApiKey?: () => string | null
}

function defaultGetApiKey(): string | null {
  // The Flask backend issues an apikey from /apikey; the user copies
  // it into local storage by visiting that page. Read from there for
  // chart-specific endpoints. Production code can swap this for a
  // server-side cookie session if needed.
  if (typeof window === 'undefined') return null
  return window.localStorage.getItem('openalgo:apikey')
}

export function WorkspaceSidebar({
  searchImpl,
  watchlistImpls,
  getApiKey,
}: WorkspaceSidebarProps = {}) {
  const [query, setQuery] = useState('')
  const [results, setResults] = useState<SymbolMatch[]>([])
  const [searching, setSearching] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const search = searchImpl ?? searchSymbols
  const apiKeyResolver = getApiKey ?? defaultGetApiKey
  const watchlistList = watchlistImpls?.list ?? listWatchlistsApi
  const watchlistSave = watchlistImpls?.save ?? saveWatchlistApi
  const watchlistRemove = watchlistImpls?.remove ?? deleteWatchlistApi

  const activeTab = useWorkspaceStore(selectActiveTab)
  const setTemplate = useWorkspaceStore((s) => s.setTemplate)
  const setCellSymbol = useWorkspaceStore((s) => s.setCellSymbol)

  const targetCellId = activeTab?.focusedCellId ?? activeTab?.cells[0]?.id ?? null

  const [watchlists, setWatchlists] = useState<WatchlistRow[]>([])
  const [watchlistError, setWatchlistError] = useState<string | null>(null)
  const [watchlistName, setWatchlistName] = useState('')

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

  // Load watchlists on mount + when the apikey appears.
  useEffect(() => {
    let cancelled = false
    const apikey = apiKeyResolver()
    if (!apikey) return undefined
    setWatchlistError(null)
    watchlistList({ apikey })
      .then((rows) => {
        if (!cancelled) setWatchlists(rows)
      })
      .catch((err) => {
        if (!cancelled) {
          setWatchlistError(err instanceof Error ? err.message : String(err))
        }
      })
    return () => {
      cancelled = true
    }
  }, [apiKeyResolver, watchlistList])

  const handleCreateWatchlist = useCallback(
    async (e: FormEvent) => {
      e.preventDefault()
      const name = watchlistName.trim()
      if (!name) return
      const apikey = apiKeyResolver()
      if (!apikey) {
        setWatchlistError('Sign in via /apikey to save watchlists.')
        return
      }
      setWatchlistError(null)
      try {
        const row = await watchlistSave({ apikey, name, symbols: [] })
        setWatchlists((prev) => [...prev.filter((w) => w.id !== row.id), row])
        setWatchlistName('')
      } catch (err) {
        setWatchlistError(err instanceof Error ? err.message : String(err))
      }
    },
    [watchlistName, apiKeyResolver, watchlistSave]
  )

  const handleDeleteWatchlist = useCallback(
    async (id: number) => {
      const apikey = apiKeyResolver()
      if (!apikey) return
      try {
        await watchlistRemove({ apikey, id })
        setWatchlists((prev) => prev.filter((w) => w.id !== id))
      } catch (err) {
        setWatchlistError(err instanceof Error ? err.message : String(err))
      }
    },
    [apiKeyResolver, watchlistRemove]
  )

  const handlePickFromWatchlist = useCallback(
    (symbol: string) => {
      if (!activeTab || !targetCellId) return
      setCellSymbol(activeTab.id, targetCellId, symbol, null)
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

      <section data-testid="watchlist-section">
        <header className="mb-1 flex items-center justify-between px-1 text-xs font-medium uppercase tracking-wide text-muted-foreground">
          <span>Watchlists</span>
        </header>
        {watchlistError && (
          <p data-testid="watchlist-error" className="mb-1 text-xs text-destructive">
            {watchlistError}
          </p>
        )}
        <ul className="max-h-48 space-y-1 overflow-y-auto" data-testid="watchlist-list">
          {watchlists.map((wl) => (
            <li
              key={wl.id}
              data-testid={`watchlist-row-${wl.id}`}
              className="rounded-sm border bg-background p-2 text-xs"
            >
              <div className="flex items-center justify-between">
                <span className="flex items-center gap-1 font-medium">
                  <Star className="h-3 w-3 text-yellow-500" />
                  {wl.name}
                </span>
                <button
                  type="button"
                  onClick={() => handleDeleteWatchlist(wl.id)}
                  aria-label={`Delete watchlist ${wl.name}`}
                  className="opacity-60 hover:opacity-100"
                  data-testid={`watchlist-delete-${wl.id}`}
                >
                  <Trash2 className="h-3 w-3" />
                </button>
              </div>
              {wl.symbols.length > 0 && (
                <ul className="mt-1 flex flex-wrap gap-1">
                  {wl.symbols.map((s) => (
                    <li key={s}>
                      <button
                        type="button"
                        onClick={() => handlePickFromWatchlist(s)}
                        className="rounded-sm border px-1.5 py-0.5 text-[11px] hover:bg-muted/40"
                        data-testid={`watchlist-symbol-${wl.id}-${s}`}
                      >
                        {s}
                      </button>
                    </li>
                  ))}
                </ul>
              )}
            </li>
          ))}
          {watchlists.length === 0 && (
            <li
              data-testid="watchlist-empty"
              className="rounded-sm border border-dashed p-3 text-xs text-muted-foreground"
            >
              No watchlists yet. Create one below.
            </li>
          )}
        </ul>
        <form onSubmit={handleCreateWatchlist} className="mt-2 flex items-center gap-1">
          <Input
            value={watchlistName}
            onChange={(e) => setWatchlistName(e.target.value)}
            placeholder="New watchlist name"
            aria-label="Watchlist name"
            className="text-xs"
            data-testid="watchlist-name-input"
          />
          <Button
            type="submit"
            size="sm"
            disabled={!watchlistName.trim()}
            data-testid="watchlist-create"
          >
            <Plus className="h-3 w-3" />
          </Button>
        </form>
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
