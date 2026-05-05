// Phase 1 — Datafeed Foundation
// Snapshot quote wire shape per HANDOFF §0.5.

import type { UTCSeconds } from './interval'

export interface NormalizedQuote {
  /** UTC seconds */
  t: UTCSeconds
  /** Best bid price (decimal string), or null when broker doesn't supply */
  bid: string | null
  /** Best ask price (decimal string), or null */
  ask: string | null
  /** Last trade price (decimal string), or null */
  last: string | null
  /** Best bid size (decimal string), or null */
  bid_size: string | null
  /** Best ask size (decimal string), or null */
  ask_size: string | null
  /** Last trade size (decimal string), or null */
  last_size: string | null
  /** Cumulative session volume (decimal string), or null */
  volume_today: string | null
}

export function isNormalizedQuote(value: unknown): value is NormalizedQuote {
  if (!value || typeof value !== 'object') return false
  const v = value as Record<string, unknown>
  if (typeof v.t !== 'number') return false
  const decFields: Array<keyof NormalizedQuote> = [
    'bid',
    'ask',
    'last',
    'bid_size',
    'ask_size',
    'last_size',
    'volume_today',
  ]
  for (const f of decFields) {
    const val = (v as Record<string, unknown>)[f]
    if (val !== null && typeof val !== 'string') return false
  }
  return true
}
