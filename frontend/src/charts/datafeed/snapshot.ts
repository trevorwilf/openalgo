// Phase 1 — Datafeed Foundation
// Engine-independent snapshot quote fetcher; calls /api/v2/quotes.

import { utcSeconds } from '../types/interval'
import type { NormalizedQuote } from '../types/quote'
import type { InstrumentRefInput } from './historical'

export interface GetSnapshotArgs {
  refs: InstrumentRefInput[]
  fetchImpl?: typeof fetch
}

export interface SnapshotEntry {
  instrument: {
    instrument_id: string | null
    venue_code: string
    canonical_symbol: string
  }
  quote: NormalizedQuote | null
  error?: { code: string; message: string }
}

function normalizeQuote(raw: Record<string, unknown>, tsIso?: string): NormalizedQuote {
  const t = tsIso ? Math.trunc(Date.parse(tsIso) / 1000) : Math.trunc(Date.now() / 1000)
  const pick = (k: string): string | null => {
    const v = raw[k]
    if (v == null) return null
    return typeof v === 'string' ? v : String(v)
  }
  return {
    t: utcSeconds(t),
    bid: pick('bid'),
    ask: pick('ask'),
    last: pick('last') ?? pick('ltp'),
    bid_size: pick('bid_size') ?? pick('bid_qty'),
    ask_size: pick('ask_size') ?? pick('ask_qty'),
    last_size: pick('last_size') ?? pick('ltq'),
    volume_today: pick('volume_today') ?? pick('volume'),
  }
}

/**
 * Fetch snapshot quotes for one or more instruments from /api/v2/quotes.
 */
export async function getSnapshotQuote(args: GetSnapshotArgs): Promise<SnapshotEntry[]> {
  const fetchFn = args.fetchImpl ?? fetch
  const resp = await fetchFn('/api/v2/quotes', {
    method: 'POST',
    credentials: 'same-origin',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ instruments: args.refs }),
  })
  if (!resp.ok) {
    const text = await resp.text().catch(() => '')
    throw new Error(`/api/v2/quotes ${resp.status}: ${text}`)
  }
  const json = (await resp.json()) as { status?: string; data?: Array<Record<string, unknown>> }
  const items = json.data ?? []
  return items.map((row) => {
    const inst = row.instrument as SnapshotEntry['instrument']
    if (row.error) {
      return {
        instrument: inst,
        quote: null,
        error: row.error as { code: string; message: string },
      }
    }
    const q = (row.quote as Record<string, unknown>) ?? {}
    return {
      instrument: inst,
      quote: normalizeQuote(q, row.timestamp as string | undefined),
    }
  })
}
