// Phase 1 — Datafeed Foundation
// Engine-independent venue-aware timezone helpers.
//
// P-06: NEVER use `5.5*60*60*1000`, 'Asia/Kolkata', or 'IST' literals.
// Display timezone resolves through the broker's region capabilities and
// the venue session service; the helpers here just take an IANA tz string
// the caller already obtained from those sources.

import type { UTCSeconds } from '../types/interval'

export interface DisplayTimeParts {
  /** ISO date (YYYY-MM-DD) in the display timezone. */
  date: string
  /** Local-clock time HH:MM:SS in the display timezone. */
  time: string
  /** Numeric UTC offset in minutes for the display timezone at that instant. */
  offsetMinutes: number
}

/**
 * Convert UTC seconds to the display-timezone parts for the venue.
 * `tz` is an IANA zone string (e.g. 'America/New_York', 'UTC').
 *
 * Implementation uses `Intl.DateTimeFormat` so DST and offsets resolve
 * correctly without hardcoded shifts. NEVER add a constant offset for
 * any specific venue — get it from the venue record.
 */
export function utcSecondsToDisplay(ts: UTCSeconds, tz: string): DisplayTimeParts {
  const d = new Date(ts * 1000)
  const fmt = new Intl.DateTimeFormat('en-CA', {
    timeZone: tz,
    year: 'numeric',
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
    second: '2-digit',
    hour12: false,
    timeZoneName: 'shortOffset',
  })
  const parts = Object.fromEntries(fmt.formatToParts(d).map((p) => [p.type, p.value])) as Record<
    string,
    string
  >
  return {
    date: `${parts.year}-${parts.month}-${parts.day}`,
    time: `${parts.hour === '24' ? '00' : parts.hour}:${parts.minute}:${parts.second}`,
    offsetMinutes: parseShortOffsetToMinutes(parts.timeZoneName),
  }
}

/** Parse a 'GMT+5:30' / 'GMT-04:00' / 'GMT' style short-offset to minutes. */
function parseShortOffsetToMinutes(s: string | undefined): number {
  if (!s) return 0
  const m = /GMT([+-])(\d{1,2})(?::?(\d{2}))?/.exec(s)
  if (!m) return 0
  const sign = m[1] === '-' ? -1 : 1
  const h = Number(m[2] || 0)
  const mm = Number(m[3] || 0)
  return sign * (h * 60 + mm)
}
