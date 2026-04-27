// v5 Phase 2 — venue/region timezone helpers (capability-driven).
//
// Replaces the per-component "Asia/Kolkata" / "+5:30" / "IST" literal
// strings that several pages used to hardcode.  The active timezone is
// derived from broker capabilities; missing context renders an
// explicit unknown state.
//
// India parity (D-4): India brokers expose `Asia/Kolkata` via their
// region/venue metadata, so India displays remain "IST" in the UI
// shape they had before.

import { useMemo } from 'react'

import { useBrokerStore } from '@/stores/brokerStore'

const IANA_TO_DISPLAY: Record<string, string> = {
  'Asia/Kolkata': 'IST',
  'America/New_York': 'ET',
  'Europe/London': 'GB',
  'Europe/Paris': 'CET',
  'Asia/Tokyo': 'JST',
  'Asia/Singapore': 'SGT',
  'Asia/Hong_Kong': 'HKT',
  'Australia/Sydney': 'AEST',
  UTC: 'UTC',
}

/**
 * Returns the active broker's IANA timezone or `null`.
 *
 * Resolution order:
 *   1. `capabilities.features.timezone` (if a region plugin set it)
 *   2. `capabilities.features.venue_timezone`
 *   3. `null` — caller renders an explicit "timezone unknown" state.
 *
 * The `features` map is intentionally permissive (the backend
 * `BrokerCapabilities.features` is a free-form dict). Real region
 * plugins set `features.timezone` to the venue's IANA name (e.g.,
 * `Asia/Kolkata`, `America/New_York`); the lookup is keyed on whatever
 * the active region plugin chose to expose.
 */
export function useActiveTimezone(): string | null {
  const tz = useBrokerStore((s) => {
    const features = s.capabilities?.features ?? {}
    const candidate = features['timezone'] ?? features['venue_timezone']
    return typeof candidate === 'string' ? candidate : null
  })
  return tz
}

/**
 * Returns a short display label for the active timezone (e.g., "IST",
 * "ET", "CET"). Falls back to the IANA name if the timezone is not in
 * the known short-label map; returns null when the timezone is
 * unknown.
 */
export function useActiveTimezoneLabel(): string | null {
  const tz = useActiveTimezone()
  return useMemo(() => {
    if (!tz) return null
    return IANA_TO_DISPLAY[tz] ?? tz
  }, [tz])
}

/**
 * Pure helper version (no React) for use in non-component contexts
 * (e.g., chart formatters, websocket handlers).
 */
export function timezoneShortLabel(tz: string | null | undefined): string | null {
  if (!tz) return null
  return IANA_TO_DISPLAY[tz] ?? tz
}
