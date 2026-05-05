// Phase 1 — Datafeed Foundation
// Live tick wire shape per HANDOFF §0.5.

import type { UTCMillis } from './interval'

export type TickKind = 'trade' | 'quote' | 'bar_forming' | 'bar_closed'

export interface TickPayloadTrade {
  price: string
  size: string
}

export interface TickPayloadQuote {
  bid: string | null
  ask: string | null
  bid_size: string | null
  ask_size: string | null
}

export interface TickPayloadBar {
  o: string
  h: string
  l: string
  c: string
  v: string
  /** UTC seconds — bar bucket start */
  bucket_t: number
  /** Bucket interval label (e.g. '1m') */
  interval: string
}

export type TickPayload =
  | TickPayloadTrade
  | TickPayloadQuote
  | TickPayloadBar
  | Record<string, unknown>

export interface NormalizedTick {
  kind: TickKind
  /** Symbol identifier (canonical_symbol from broker capabilities) */
  symbol: string
  /** UTC milliseconds (epoch) — wire uses ms for ticks per §0.5 */
  t: UTCMillis
  payload: TickPayload
}

export function isNormalizedTick(value: unknown): value is NormalizedTick {
  if (!value || typeof value !== 'object') return false
  const v = value as Record<string, unknown>
  return (
    (v.kind === 'trade' ||
      v.kind === 'quote' ||
      v.kind === 'bar_forming' ||
      v.kind === 'bar_closed') &&
    typeof v.symbol === 'string' &&
    typeof v.t === 'number' &&
    typeof v.payload === 'object' &&
    v.payload !== null
  )
}
