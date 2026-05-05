// Phase 1 — Datafeed Foundation
// Bar wire shape per HANDOFF §0.5.
// Decimal fields are STRING (never number) at the wire layer to preserve
// precision; UI parsers can convert at the very last moment for rendering.

import type { UTCSeconds } from './interval'

export interface NormalizedBar {
  /** UTC seconds (epoch) */
  t: UTCSeconds
  /** Open price as decimal string */
  o: string
  /** High price as decimal string */
  h: string
  /** Low price as decimal string */
  l: string
  /** Close price as decimal string */
  c: string
  /** Volume as decimal string */
  v: string
  /** Open interest as decimal string, or null when not applicable */
  oi: string | null
}

/** Convert a decimal-string field to a JS number for rendering. */
export function decStrToNumber(s: string | null): number | null {
  if (s == null) return null
  const n = Number(s)
  return Number.isFinite(n) ? n : null
}

/** True iff the bar is a structurally-valid NormalizedBar. */
export function isNormalizedBar(value: unknown): value is NormalizedBar {
  if (!value || typeof value !== 'object') return false
  const v = value as Record<string, unknown>
  return (
    typeof v.t === 'number' &&
    typeof v.o === 'string' &&
    typeof v.h === 'string' &&
    typeof v.l === 'string' &&
    typeof v.c === 'string' &&
    typeof v.v === 'string' &&
    (v.oi === null || typeof v.oi === 'string')
  )
}
