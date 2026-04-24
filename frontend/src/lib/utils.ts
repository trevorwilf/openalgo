import { type ClassValue, clsx } from 'clsx'
import { twMerge } from 'tailwind-merge'

export function cn(...inputs: ClassValue[]) {
  return twMerge(clsx(inputs))
}

/**
 * Sanitize a value for CSV export to prevent formula injection.
 * Prefixes dangerous characters (=, +, -, @) with a single quote.
 */
export function sanitizeCSV(value: string | number | null | undefined): string {
  if (value === null || value === undefined) return ''
  const str = String(value)
  // Prefix dangerous formula characters with a single quote
  if (/^[=+\-@]/.test(str)) {
    return `'${str}`
  }
  // Escape quotes and wrap in quotes if contains comma
  if (str.includes(',') || str.includes('"') || str.includes('\n')) {
    return `"${str.replace(/"/g, '""')}"`
  }
  return str
}

// Crypto and stablecoin codes — Intl.NumberFormat does not recognize
// these, so we format them with a ticker suffix and a
// crypto-appropriate precision.
const CRYPTO_PRECISION: Record<string, number> = {
  BTC: 8,
  ETH: 6,
  USDT: 2,
  USDC: 2,
}

/**
 * Format a numeric value in the given currency code.
 *
 * Handles ISO-4217 currencies via `Intl.NumberFormat` (which picks the
 * right symbol / locale-aware formatting), and falls back to a
 * ticker-suffix format for crypto codes that `Intl` doesn't recognize.
 *
 * `locale` is optional — when omitted the runtime's default locale is
 * used for fiat currencies. Crypto uses a fixed "X.XX CODE" format so
 * parity tests are deterministic.
 */
export function formatCurrencyByCode(
  value: number,
  currency: string,
  locale?: string,
): string {
  const code = currency.toUpperCase()
  if (code in CRYPTO_PRECISION) {
    const digits = CRYPTO_PRECISION[code]
    return `${value.toFixed(digits)} ${code}`
  }
  // Pick a reasonable default locale for common currencies when the
  // caller doesn't specify one. JPY defaults to 0 decimals per
  // Intl.NumberFormat rules — we let the runtime apply that.
  const defaultLocale =
    code === 'INR' ? 'en-IN' : code === 'JPY' ? 'ja-JP' : 'en-US'
  return new Intl.NumberFormat(locale ?? defaultLocale, {
    style: 'currency',
    currency: code,
    minimumFractionDigits: code === 'JPY' ? 0 : 2,
  }).format(value)
}

// Deprecated: `makeFormatCurrency` branches on broker name. New code
// should use `formatCurrencyByCode(value, currencyCode)` with the
// currency from the instrument / account. A one-shot warning surfaces
// the migration path without spamming the console.
let _deprecationWarned = false

export function _resetDeprecationWarningForTests(): void {
  _deprecationWarned = false
}

/**
 * @deprecated Use `formatCurrencyByCode(value, currencyCode)` instead.
 * Kept so existing call sites keep compiling during the Phase 7+
 * migration.
 */
export function makeFormatCurrency(broker?: string | null): (value: number) => string {
  if (!_deprecationWarned) {
    _deprecationWarned = true
    // biome-ignore lint/suspicious/noConsole: deprecation path
    console.warn(
      'makeFormatCurrency is deprecated — use formatCurrencyByCode(value, currencyCode).',
    )
  }
  const isUSD = broker === 'deltaexchange'
  const currency = isUSD ? 'USD' : 'INR'
  return (value: number) => formatCurrencyByCode(value, currency)
}
