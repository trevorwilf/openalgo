// Phase 1 — Datafeed Foundation
// Engine-independent symbol search; wraps /search/api/search.

export interface SymbolMatch {
  /** Canonical symbol */
  symbol: string
  /** Display name / company */
  name: string
  /** Venue code */
  exchange: string
  /** Optional broker token (string for portability) */
  token?: string | null
  /** Lot size, if relevant */
  lotsize?: number | null
  /** Instrument type (EQ, FUT, OPTIDX, etc.) */
  instrumenttype?: string | null
}

export interface SearchSymbolsArgs {
  query: string
  /** Filter to a single venue (matches `exchange` field) */
  venue?: string
  /** Maximum number of results */
  limit?: number
  fetchImpl?: typeof fetch
}

/**
 * Search the symbol universe via /search/api/search.
 *
 * The endpoint is shared with legacy pages — it remains stable. New
 * chart code routes through this wrapper so test code can mock one
 * boundary instead of pulling in the search blueprint directly.
 */
export async function searchSymbols(args: SearchSymbolsArgs): Promise<SymbolMatch[]> {
  const fetchFn = args.fetchImpl ?? fetch
  const params = new URLSearchParams({ q: args.query })
  if (args.venue) params.set('exchange', args.venue)
  if (args.limit != null) params.set('limit', String(args.limit))
  const resp = await fetchFn(`/search/api/search?${params.toString()}`, {
    method: 'GET',
    credentials: 'same-origin',
    headers: { Accept: 'application/json' },
  })
  if (!resp.ok) {
    if (resp.status === 404) return []
    const text = await resp.text().catch(() => '')
    throw new Error(`/search/api/search ${resp.status}: ${text}`)
  }
  const json = (await resp.json()) as {
    results?: SymbolMatch[]
    data?: SymbolMatch[]
  }
  return json.results ?? json.data ?? []
}
