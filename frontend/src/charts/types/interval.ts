// Phase 1 — Datafeed Foundation
// Branded numeric types so timestamps in different units cannot mix.
// Per HANDOFF P-06: storage and wire layers use UTC seconds for bars,
// UTC milliseconds for ticks.

declare const utcSecondsBrand: unique symbol
declare const utcMillisBrand: unique symbol

export type UTCSeconds = number & { readonly [utcSecondsBrand]: true }
export type UTCMillis = number & { readonly [utcMillisBrand]: true }

export const utcSeconds = (n: number): UTCSeconds => n as UTCSeconds
export const utcMillis = (n: number): UTCMillis => n as UTCMillis

export const secondsToMillis = (s: UTCSeconds): UTCMillis => utcMillis(Math.trunc(s) * 1000)
export const millisToSeconds = (ms: UTCMillis): UTCSeconds => utcSeconds(Math.trunc(ms / 1000))

/**
 * Canonical interval vocabulary per HANDOFF D-08.
 *
 * Every interval the chart UI ever surfaces appears in this list; broker
 * adapters translate to/from their native vocabularies via
 * `intervals.ts → translateForBroker`.
 */
export const CANONICAL_INTERVALS = [
  '1s',
  '5s',
  '15s',
  '30s',
  '1m',
  '2m',
  '3m',
  '5m',
  '10m',
  '15m',
  '30m',
  '1h',
  '2h',
  '4h',
  '1d',
  '1w',
  '1mo',
] as const

export type CanonicalInterval = (typeof CANONICAL_INTERVALS)[number]

export function isCanonicalInterval(s: string): s is CanonicalInterval {
  return (CANONICAL_INTERVALS as readonly string[]).includes(s)
}

/** Number of seconds in a single bucket of `interval`, or null for calendar-aware ('1mo'). */
export function intervalSeconds(interval: CanonicalInterval): number | null {
  switch (interval) {
    case '1s':
      return 1
    case '5s':
      return 5
    case '15s':
      return 15
    case '30s':
      return 30
    case '1m':
      return 60
    case '2m':
      return 120
    case '3m':
      return 180
    case '5m':
      return 300
    case '10m':
      return 600
    case '15m':
      return 900
    case '30m':
      return 1800
    case '1h':
      return 3600
    case '2h':
      return 7200
    case '4h':
      return 14400
    case '1d':
      return 86400
    case '1w':
      return 604800
    case '1mo':
      return null
  }
}
