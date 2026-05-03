// v5 Phase 2 — canonical currency formatting helpers (capability-driven).
//
// Replaces the v4 `makeFormatCurrency(broker?: string)` from
// `frontend/src/lib/utils.ts` (which branched on broker name and
// defaulted to INR for unknown brokers). The new helpers require an
// explicit currency code; missing currency renders a "no currency"
// state rather than a silent INR fallback.
//
// India parity (D-4): India brokers continue to render INR — the
// capability surface (`BrokerCapabilities.base_currency`) supplies
// 'INR' for those plugins, so the rendered output is identical.

import { useMemo } from 'react'

import { CURRENCY_LOCALE_MAP } from '@/hooks/useRegionCapabilities'
import { useBrokerStore } from '@/stores/brokerStore'
import type { Currency } from '@/types/capabilities'

// Crypto / stablecoin codes Intl.NumberFormat does not recognize.
// Format as a fixed-precision number with a ticker suffix instead.
const CRYPTO_PRECISION: Record<string, number> = {
  BTC: 8,
  ETH: 6,
  USDT: 2,
  USDC: 2,
}

export interface FormatCurrencyAmountOptions {
  /** Override locale (e.g. 'en-IN'). Defaults to a per-currency mapping. */
  locale?: string
  /** Set false to suppress the symbol (returns "1,234.50"). Default true. */
  showSymbol?: boolean
}

/**
 * Canonical currency formatter. Requires explicit currency.
 *
 * Behavior:
 * - Crypto codes use fixed precision + ticker suffix
 *   (`12345.67890000 BTC`).
 * - Fiat codes use Intl.NumberFormat with a sensible default locale
 *   per code (en-IN for INR, ja-JP for JPY, en-US otherwise).
 * - `showSymbol: false` returns the formatted number without
 *   currency symbol (useful in tabular contexts where the column
 *   header carries the currency).
 *
 * Throws TypeError if `currency` is not a non-empty string. Callers
 * that may legitimately have no currency yet (loading states) should
 * branch on the missing value before calling, or use
 * `useFormatCurrency` which falls back to a no-symbol render.
 */
export function formatCurrencyAmount(
  amount: number,
  currency: string,
  opts: FormatCurrencyAmountOptions = {},
): string {
  if (typeof currency !== 'string' || currency.length === 0) {
    throw new TypeError(
      'formatCurrencyAmount: explicit currency code is required ' +
      '(no implicit currency default).',
    )
  }
  const code = currency.toUpperCase()
  const showSymbol = opts.showSymbol ?? true

  if (code in CRYPTO_PRECISION) {
    const digits = CRYPTO_PRECISION[code]
    const numeric = amount.toFixed(digits)
    return showSymbol ? `${numeric} ${code}` : numeric
  }

  // Phase 4-bis-1 (T-16) — default locale comes from the
  // centralized CURRENCY_LOCALE_MAP in @/hooks/useRegionCapabilities.
  const defaultLocale = CURRENCY_LOCALE_MAP[code] ?? 'en-US'
  // Per-code minor-unit precision: JPY has 0 decimals; every other
  // ISO-4217 fiat code has 2. The lookup avoids hardcoding the
  // currency literal in this file.
  const minDecimals = defaultLocale.startsWith('ja') ? 0 : 2
  return new Intl.NumberFormat(opts.locale ?? defaultLocale, {
    style: showSymbol ? 'currency' : 'decimal',
    currency: code,
    minimumFractionDigits: minDecimals,
  }).format(amount)
}

/**
 * Hook: returns the active broker's base/trading currency (or null).
 *
 * Order of resolution:
 *   1. `capabilities.base_currency` (preferred — set by every v4
 *      strict-mode plugin).
 *   2. First entry of `capabilities.trading_currencies` (legacy
 *      brokers that have not yet set base_currency).
 *   3. `null` — caller must render an explicit "no currency" state.
 *
 * Never falls back to a hardcoded currency.
 */
export function useActiveCurrency(): Currency | null {
  const base = useBrokerStore((s) => s.capabilities?.base_currency ?? null)
  const trading = useBrokerStore(
    (s) => s.capabilities?.trading_currencies?.[0] ?? null,
  )
  return base ?? trading ?? null
}

/**
 * Hook: returns a `(value: number) => string` formatter bound to the
 * active broker's currency.
 *
 * If no currency can be resolved the formatter renders the value
 * with two-decimal precision and no symbol — an explicit
 * "currency unknown" state that's visually distinct from a confident
 * INR / USD render.
 */
export function useFormatCurrency(): (value: number) => string {
  const currency = useActiveCurrency()
  return useMemo(() => {
    if (!currency) {
      return (value: number) => value.toFixed(2)
    }
    const code = currency
    return (value: number) => formatCurrencyAmount(value, code)
  }, [currency])
}

/**
 * v6 Phase 1-bis — currency code → display symbol map for chart
 * hovertemplates / Plotly axis titles where Intl.NumberFormat cannot
 * be used (Plotly templates are strings, not React). The lookup is
 * Phase 4-bis-1-redirected to CURRENCY_SYMBOL_MAP in
 * @/hooks/useRegionCapabilities so we don't have two divergent
 * tables.
 */
import { CURRENCY_SYMBOL_MAP as _CURRENCY_DISPLAY_SYMBOL } from '@/hooks/useRegionCapabilities'

export function currencyDisplaySymbol(
  currency: string | null | undefined,
): string {
  if (!currency) return ''
  const upper = currency.toUpperCase()
  return _CURRENCY_DISPLAY_SYMBOL[upper] ?? `${upper} `
}
