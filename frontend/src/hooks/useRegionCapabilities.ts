// Phase 4 (T-16) — region-aware locale + currency + venue list hook.
//
// `useRegionCapabilities()` returns the active broker's region-shaped
// metadata in one place, so component code stops sprinkling per-call
// `'en-IN'` / `'INR'` / `'NSE'` literals.
//
// The hook composes:
//
//   * `useBrokerStore` — the active broker plugin's
//     `base_currency`, `supported_regions`, etc.
//   * `useVenueTimezone()` — the venue-aware IANA timezone name.
//
// India parity: when an India broker is active, the hook returns
// `{currency: 'INR', locale: 'en-IN', timezone: 'Asia/Kolkata',
//   currencySymbol: '₹'}` — bit-identical to the pre-Phase-4
// hardcoded paths.
//
// Non-India broker: `{currency: <broker default>, locale: <derived>,
//   timezone: <venue tz or null>}`. No India fallback.
//
// No-broker / capability-cold-load: every field is `null` or empty;
// callers render an explicit "select broker" / unavailable state.

import { useMemo } from 'react'

import { useBrokerStore } from '@/stores/brokerStore'

import { useVenueTimezone, useVenueTimezoneLabel } from './useVenueTimezone'

export interface RegionCapabilities {
  /** ISO-4217 currency code, or `null` when the broker hasn't loaded. */
  currency: string | null
  /** BCP-47 locale tag derived from `currency` (en-IN / en-US / ja-JP / etc.). */
  locale: string | null
  /** IANA timezone name (Asia/Kolkata / America/New_York / etc.) or `null`. */
  timezone: string | null
  /** Short timezone label (IST / ET / UTC / ...) or `null`. */
  timezoneLabel: string | null
  /** Currency symbol (₹ / $ / € / £ / ¥). Falls through to the code itself. */
  currencySymbol: string | null
  /** Active broker's `supported_regions[]` — lowercased; empty when unknown. */
  regions: readonly string[]
  /** Region-flagged active India? Convenience for code that needs an
   *  India / non-India branch. False when capabilities aren't loaded. */
  isIndiaActive: boolean
}

const _CURRENCY_LOCALE: Record<string, string> = {
  INR: 'en-IN',
  USD: 'en-US',
  EUR: 'en-GB',
  GBP: 'en-GB',
  JPY: 'ja-JP',
  CHF: 'de-CH',
  SGD: 'en-SG',
  HKD: 'en-HK',
  AUD: 'en-AU',
  USDT: 'en-US',
  USDC: 'en-US',
  BTC: 'en-US',
  ETH: 'en-US',
}

const _CURRENCY_SYMBOL: Record<string, string> = {
  INR: '₹',
  USD: '$',
  EUR: '€',
  GBP: '£',
  JPY: '¥',
  CHF: 'CHF',
  SGD: 'S$',
  HKD: 'HK$',
  AUD: 'A$',
  USDT: 'USDT',
  USDC: 'USDC',
  BTC: '₿',
  ETH: 'Ξ',
}

/**
 * Returns the active region's currency / locale / timezone / venue
 * metadata. Stable identity across re-renders so callers can pass
 * the result to memoized children.
 */
export function useRegionCapabilities(): RegionCapabilities {
  const cap = useBrokerStore((s) => s.capabilities)
  const tz = useVenueTimezone()
  const tzLabel = useVenueTimezoneLabel()

  return useMemo<RegionCapabilities>(() => {
    if (!cap) {
      return {
        currency: null,
        locale: null,
        timezone: tz,
        timezoneLabel: tzLabel,
        currencySymbol: null,
        regions: [],
        isIndiaActive: false,
      }
    }
    const currency = cap.base_currency ? String(cap.base_currency).toUpperCase() : null
    const locale = currency ? (_CURRENCY_LOCALE[currency] ?? 'en-US') : null
    const symbol = currency ? (_CURRENCY_SYMBOL[currency] ?? currency) : null
    const regions = (cap.supported_regions ?? []).map((r) => String(r).toLowerCase())
    const isIndiaActive = regions.includes('india')
    return {
      currency,
      locale,
      timezone: tz,
      timezoneLabel: tzLabel,
      currencySymbol: symbol,
      regions,
      isIndiaActive,
    }
  }, [cap, tz, tzLabel])
}

export default useRegionCapabilities
