import { useMemo } from 'react'
import { useBrokerStore } from '@/stores/brokerStore'

/** Exchange option for dropdowns */
export interface ExchangeOption {
  value: string
  label: string
}

/** Default underlyings per F&O exchange */
const UNDERLYINGS: Record<string, string[]> = {
  NFO: ['NIFTY', 'BANKNIFTY', 'FINNIFTY', 'MIDCPNIFTY'],
  BFO: ['SENSEX', 'BANKEX'],
  MCX: ['GOLDM', 'CRUDEOIL', 'SILVERM', 'NATURALGAS', 'COPPER'],
  CDS: ['USDINR', 'EURINR', 'GBPINR', 'JPYINR'],
  CRYPTO: ['BTC', 'ETH', 'SOL', 'BNB', 'XRP'],
}

/** Index exchanges excluded from trading/FNO lists */
const INDEX_EXCHANGES = new Set(['NSE_INDEX', 'BSE_INDEX', 'MCX_INDEX', 'CDS_INDEX'])

/** F&O exchange codes (includes MCX/CDS which also have options) */
const FNO_CODES = new Set(['NFO', 'BFO', 'MCX', 'CDS', 'CRYPTO'])

/**
 * Last-resort default used ONLY when explicitly opted in via
 * `allowLegacyFallback` AND the broker (current OR last-known) is
 * India-shaped. Phase 5 (ADR 0010): a broker whose `supported_regions`
 * excludes "india" never falls back to NSE/NFO/MCX — it renders an
 * "unavailable" state instead, so non-India brokers never show
 * Indian exchanges by accident.
 */
const LEGACY_FALLBACK_EXCHANGES = ['NSE', 'BSE', 'NFO', 'BFO', 'CDS', 'MCX', 'CRYPTO']

function _broker_is_india_shaped(cap: { supported_regions?: string[] | null } | null): boolean {
  if (cap == null) return true // unknown — treat as legacy India for backward compat
  const regions = (cap.supported_regions ?? []).map((r) => String(r).toLowerCase())
  if (regions.length === 0) return true
  return regions.includes('india')
}

export interface UseSupportedExchangesOptions {
  /**
   * When true, fall back to the hardcoded Indian+CRYPTO exchange list
   * when capabilities are unavailable AND the active (or last-known)
   * broker is India-shaped. Defaults to **true** for this phase to
   * preserve every existing caller's behavior; the fallback is now
   * gated by region so non-India brokers never receive Indian
   * exchange defaults regardless of opt-in.
   */
  allowLegacyFallback?: boolean
}

export function useSupportedExchanges(opts: UseSupportedExchangesOptions = {}) {
  const allowLegacyFallback = opts.allowLegacyFallback ?? true
  const capabilities = useBrokerStore((s) => s.capabilities)
  const isError = useBrokerStore((s) => s.isError)

  return useMemo(() => {
    // Prefer the rich `supported_venue_codes` when present, fall back
    // to the legacy alias `supported_exchanges`. Without capabilities
    // and without the India-shape signal we render an unavailable
    // state instead of the legacy NSE/NFO list.
    const fromCap = capabilities?.supported_venue_codes ?? capabilities?.supported_exchanges
    const usingFallback = fromCap === undefined
    const indiaShaped = _broker_is_india_shaped(capabilities)
    const supported =
      fromCap ?? (allowLegacyFallback && indiaShaped ? LEGACY_FALLBACK_EXCHANGES : [])
    const isCrypto = capabilities?.broker_type === 'crypto'

    // All exchanges from plugin.json
    const allExchanges: ExchangeOption[] = supported.map((e) => ({ value: e, label: e }))

    // Trading exchanges: exclude _INDEX suffixed exchanges
    const tradingExchanges: ExchangeOption[] = supported
      .filter((e) => !INDEX_EXCHANGES.has(e))
      .map((e) => ({ value: e, label: e }))

    // F&O exchanges: NFO, BFO, or CRYPTO (only those the broker supports)
    const fnoExchanges: ExchangeOption[] = supported
      .filter((e) => FNO_CODES.has(e))
      .map((e) => ({ value: e, label: e }))

    // Exchanges shown inside /tools pages (Strategy Builder, Option Chain,
    // OI Tracker, Straddle Chart, Custom Straddle etc.). MCX and CDS are
    // temporarily excluded — the option chain + quotes plumbing doesn't
    // fully support them yet. CRYPTO is retained for crypto-only brokers.
    const toolsFnoExchanges: ExchangeOption[] = fnoExchanges.filter(
      (e) => e.value !== 'MCX' && e.value !== 'CDS'
    )

    // Defaults — only fall back to NSE/NFO when the broker is
    // India-shaped (legacy plugin or supported_regions includes "india").
    // Non-India brokers without venue codes get an empty default
    // ('') so the UI shows an unavailable state rather than NSE.
    const fallbackTrading = isCrypto ? 'CRYPTO' : indiaShaped ? 'NSE' : ''
    const fallbackFno = isCrypto ? 'CRYPTO' : indiaShaped ? 'NFO' : ''
    const defaultExchange = tradingExchanges[0]?.value ?? fallbackTrading
    const defaultFnoExchange = fnoExchanges[0]?.value ?? fallbackFno
    const defaultToolsFnoExchange = toolsFnoExchanges[0]?.value ?? fallbackFno

    // Underlyings filtered to only supported FNO exchanges
    const defaultUnderlyings: Record<string, string[]> = {}
    for (const ex of fnoExchanges) {
      if (UNDERLYINGS[ex.value]) {
        defaultUnderlyings[ex.value] = UNDERLYINGS[ex.value]
      }
    }

    return {
      /** All exchanges from plugin.json (including _INDEX) */
      allExchanges,
      /** Trading exchanges (no _INDEX) — for TradingView, GoCharting, Search */
      tradingExchanges,
      /** Broker-reported F&O exchanges (NFO, BFO, MCX, CDS, CRYPTO). */
      fnoExchanges,
      /**
       * F&O exchanges allowed in /tools pages today — NFO, BFO, CRYPTO only.
       * Prefer this over `fnoExchanges` in every route under /tools/* .
       */
      toolsFnoExchanges,
      /** First trading exchange */
      defaultExchange,
      /** First F&O exchange */
      defaultFnoExchange,
      /** First tools-supported F&O exchange */
      defaultToolsFnoExchange,
      /** Underlyings map filtered to supported F&O exchanges */
      defaultUnderlyings,
      /** Quick check: is this a crypto broker? */
      isCrypto,
      /** Phase 5: true when capabilities are unavailable (fetch failed). */
      isError,
      /** Phase 5: true when the returned lists are the legacy fallback,
       * not capability-derived. */
      isFallback: usingFallback,
    }
  }, [capabilities, isError, allowLegacyFallback])
}
