// Phase 3 — minimal watchlist client wired to /api/v2/chart/watchlists.
// Phase 5 wires the rest of the chart CRUD; the watchlist endpoint is
// the only DB-backed persistence Phase 3 surfaces (per the prompt).

export interface WatchlistRow {
  id: number
  user_id: string
  name: string
  symbols: string[]
  created_at: string | null
  updated_at: string | null
}

export interface ListWatchlistsArgs {
  apikey: string
  fetchImpl?: typeof fetch
}

export interface SaveWatchlistArgs {
  apikey: string
  name: string
  symbols: string[]
  fetchImpl?: typeof fetch
}

export async function listWatchlists(args: ListWatchlistsArgs): Promise<WatchlistRow[]> {
  const fetchFn = args.fetchImpl ?? fetch
  const params = new URLSearchParams({ apikey: args.apikey })
  const resp = await fetchFn(`/api/v2/chart/watchlists?${params.toString()}`, {
    method: 'GET',
    credentials: 'same-origin',
    headers: { Accept: 'application/json' },
  })
  if (!resp.ok) {
    const text = await resp.text().catch(() => '')
    throw new Error(`/api/v2/chart/watchlists ${resp.status}: ${text}`)
  }
  const json = (await resp.json()) as { data?: WatchlistRow[] }
  return json.data ?? []
}

export async function saveWatchlist(args: SaveWatchlistArgs): Promise<WatchlistRow> {
  const fetchFn = args.fetchImpl ?? fetch
  const resp = await fetchFn('/api/v2/chart/watchlists', {
    method: 'POST',
    credentials: 'same-origin',
    headers: { 'Content-Type': 'application/json', Accept: 'application/json' },
    body: JSON.stringify({
      apikey: args.apikey,
      name: args.name,
      symbols: args.symbols,
    }),
  })
  if (!resp.ok) {
    const text = await resp.text().catch(() => '')
    throw new Error(`/api/v2/chart/watchlists ${resp.status}: ${text}`)
  }
  const json = (await resp.json()) as { data: WatchlistRow }
  return json.data
}

export async function deleteWatchlist(args: {
  apikey: string
  id: number
  fetchImpl?: typeof fetch
}): Promise<void> {
  const fetchFn = args.fetchImpl ?? fetch
  const params = new URLSearchParams({ apikey: args.apikey })
  const resp = await fetchFn(`/api/v2/chart/watchlists/${args.id}?${params.toString()}`, {
    method: 'DELETE',
    credentials: 'same-origin',
  })
  if (!resp.ok && resp.status !== 204) {
    const text = await resp.text().catch(() => '')
    throw new Error(`/api/v2/chart/watchlists/${args.id} DELETE ${resp.status}: ${text}`)
  }
}
