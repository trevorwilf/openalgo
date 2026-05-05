// Phase 1 — Datafeed Foundation
// Engine-independent historical bar fetcher; calls /api/v2/bars.

import type { NormalizedBar } from '../types/bar'
import type { CanonicalInterval } from '../types/interval'
import { utcSeconds } from '../types/interval'

export interface InstrumentRefInput {
  /** Optional UUID of an already-resolved instrument */
  instrument_id?: string
  /** Venue code (e.g. 'XNAS', 'XNYS', 'XNSE') */
  venue_code?: string
  /** Canonical symbol (broker-agnostic) */
  canonical_symbol?: string
  /** Identifier-kind lookup (ISIN/FIGI/etc.) */
  identifier_type?: string
  identifier_value?: string
  broker_code?: string
}

export interface GetBarsArgs {
  ref: InstrumentRefInput
  interval: CanonicalInterval
  /** ISO-8601 UTC string (e.g. '2024-01-01T00:00:00Z') or epoch seconds */
  from: string | number
  /** Inclusive end bound */
  to: string | number
  /** Optional fetch override for tests */
  fetchImpl?: typeof fetch
}

export interface GetBarsResult {
  instrument: {
    instrument_id: string | null
    venue_code: string
    canonical_symbol: string
  }
  interval: string
  bars: NormalizedBar[]
}

function toIso(v: string | number): string {
  if (typeof v === 'string') return v
  return new Date(v * 1000).toISOString()
}

/**
 * Map the /api/v2/bars response into the wire NormalizedBar shape.
 * The backend currently emits {ts, open, high, low, close, volume} on
 * the legacy fallback path and {t, o, h, l, c, v} on the promoted path.
 * Normalize both to {t, o, h, l, c, v, oi}.
 */
function normalizeBar(raw: Record<string, unknown>): NormalizedBar {
  const t =
    typeof raw.t === 'number'
      ? raw.t
      : typeof raw.ts === 'string'
        ? Math.trunc(Date.parse(raw.ts) / 1000)
        : typeof raw.ts === 'number'
          ? raw.ts
          : 0
  const pick = (k1: string, k2: string): string => {
    const v = raw[k1] ?? raw[k2]
    if (v == null) return '0'
    return typeof v === 'string' ? v : String(v)
  }
  const oiVal = raw.oi ?? raw.open_interest ?? null
  return {
    t: utcSeconds(t),
    o: pick('o', 'open'),
    h: pick('h', 'high'),
    l: pick('l', 'low'),
    c: pick('c', 'close'),
    v: pick('v', 'volume'),
    oi: oiVal == null ? null : typeof oiVal === 'string' ? oiVal : String(oiVal),
  }
}

/**
 * Fetch historical OHLCV bars from /api/v2/bars.
 *
 * Throws on transport / auth errors. Returns an empty `bars` array if
 * the broker resolves the instrument but has no data in range.
 */
export async function getBars(args: GetBarsArgs): Promise<GetBarsResult> {
  const fetchFn = args.fetchImpl ?? fetch
  const body = {
    instrument: args.ref,
    interval: args.interval,
    start: toIso(args.from),
    end: toIso(args.to),
  }
  const resp = await fetchFn('/api/v2/bars', {
    method: 'POST',
    credentials: 'same-origin',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  })
  if (!resp.ok) {
    const text = await resp.text().catch(() => '')
    throw new Error(`/api/v2/bars ${resp.status}: ${text}`)
  }
  const json = (await resp.json()) as {
    status?: string
    data?: {
      instrument: { instrument_id: string | null; venue_code: string; canonical_symbol: string }
      interval: string
      bars: Array<Record<string, unknown>>
    }
  }
  const data = json.data
  if (!data) {
    throw new Error('/api/v2/bars: missing data envelope')
  }
  return {
    instrument: data.instrument,
    interval: data.interval,
    bars: data.bars.map(normalizeBar),
  }
}
