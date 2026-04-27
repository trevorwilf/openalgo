/**
 * Frontend capability types — mirrors the backend `domain.BrokerCapabilities`
 * (Phase 1b). Keep these in sync with `domain/capabilities.py` and
 * `docs/plugin-schema/plugin.schema.json`.
 *
 * Design targets match Phase 1a: Indian, US, European equities, and
 * crypto. Adding a new family / asset class / order type is a one-line
 * extension to the relevant union here.
 */

export type MarketFamily =
  | 'IN_STOCK'
  | 'US_STOCK'
  | 'EU_STOCK'
  | 'UK_STOCK'
  | 'CRYPTO'
  | 'FUTURES'
  | 'FX'
  | 'COMMODITY'
  | 'OTHER'

export type AssetClass =
  | 'EQUITY'
  | 'ETF'
  | 'FUTURE'
  | 'OPTION'
  | 'PERPETUAL'
  | 'SPOT'
  | 'INDEX'
  | 'BOND'
  | 'WARRANT'
  | 'STRUCTURED'
  | 'OTHER'

export type PlatformOrderType =
  | 'MARKET'
  | 'LIMIT'
  | 'STOP'
  | 'STOP_LIMIT'
  | 'TRAILING_STOP'
  | 'MARKET_ON_OPEN'
  | 'MARKET_ON_CLOSE'
  | 'LIMIT_ON_OPEN'
  | 'LIMIT_ON_CLOSE'
  | 'PEGGED'

export type PlatformTimeInForce = 'DAY' | 'GTC' | 'GTD' | 'IOC' | 'FOK' | 'OPG' | 'ATC'

export type PlatformSession =
  | 'PRE_MARKET'
  | 'OPENING_AUCTION'
  | 'REGULAR'
  | 'INTRADAY_AUCTION'
  | 'CLOSING_AUCTION'
  | 'POST_MARKET'
  | 'EXTENDED'
  | 'ALL_DAY'

export type PlatformQuantityUnit = 'WHOLE' | 'FRACTIONAL' | 'NOTIONAL' | 'CONTRACTS' | 'LOTS'

/** ISO-4217 fiat codes plus common crypto tickers. Mirror `domain.Currency`. */
export type Currency =
  | 'INR'
  | 'USD'
  | 'EUR'
  | 'GBP'
  | 'CHF'
  | 'SGD'
  | 'HKD'
  | 'JPY'
  | 'AUD'
  | 'USDT'
  | 'USDC'
  | 'BTC'
  | 'ETH'

/**
 * Rich broker capabilities as returned by `GET /api/broker/capabilities`
 * after Phase 1b. Keeps the four legacy aliases (`broker_name`,
 * `broker_type`, `supported_exchanges`, `leverage_config`) so existing
 * components that read them continue to work.
 */
export interface BrokerCapabilities {
  // Legacy aliases — preserved so existing components compile.
  broker_name: string
  broker_type: 'IN_stock' | 'crypto' | string // backend may return new families later
  supported_exchanges: string[]
  leverage_config: boolean

  // Phase 1b rich surface
  broker_code: string
  broker_display_name: string
  market_families: MarketFamily[]
  supported_regions: string[]
  supported_venue_codes: string[]
  supported_asset_classes: AssetClass[]
  supported_order_types: PlatformOrderType[]
  supported_time_in_force: PlatformTimeInForce[]
  supported_sessions: PlatformSession[]
  supported_quantity_units: PlatformQuantityUnit[]
  trading_currencies: Currency[]
  base_currency: Currency | null
  supports_fractional: boolean
  supports_notional_orders: boolean
  supports_extended_hours: boolean
  supports_short_selling: boolean
  supports_analyzer: boolean
  // v5 Phase 4 — sandbox/paper-trading feature flag (per-broker).
  supports_sandbox: boolean
  features: Record<string, boolean>
}

// ---------------------------------------------------------------------------
// Capability helpers
// ---------------------------------------------------------------------------

/** True iff the broker's capabilities list a given order type. */
export function isOrderTypeSupported(
  cap: BrokerCapabilities | null,
  ot: PlatformOrderType
): boolean {
  if (!cap) return false
  return cap.supported_order_types.includes(ot)
}

/** True iff the broker's capabilities list a given TIF. */
export function isTimeInForceSupported(
  cap: BrokerCapabilities | null,
  tif: PlatformTimeInForce
): boolean {
  if (!cap) return false
  return cap.supported_time_in_force.includes(tif)
}

/** True iff the broker's capabilities list a given session. */
export function isSessionSupported(
  cap: BrokerCapabilities | null,
  session: PlatformSession
): boolean {
  if (!cap) return false
  return cap.supported_sessions.includes(session)
}

/** True iff the broker has a first-class capability flag set to true. */
export function hasCapability(
  cap: BrokerCapabilities | null,
  name:
    | 'supports_fractional'
    | 'supports_notional_orders'
    | 'supports_extended_hours'
    | 'supports_short_selling'
    | 'supports_analyzer'
    | 'supports_sandbox'
    | 'leverage_config'
): boolean {
  if (!cap) return false
  return cap[name] === true
}

/**
 * Map a PlatformOrderType to the legacy Indian string that the /api/v1
 * place_order endpoint accepts. Returns null for order types the
 * legacy /api/v1 cannot represent. Used by order-form components that
 * still POST to /api/v1.
 *
 * Mirrors the backend `domain.translators.normalized_order_to_legacy_fields`.
 */
export function platformOrderTypeToLegacy(ot: PlatformOrderType): string | null {
  switch (ot) {
    case 'MARKET':
      return 'MARKET'
    case 'LIMIT':
      return 'LIMIT'
    case 'STOP':
      return 'SL-M'
    case 'STOP_LIMIT':
      return 'SL'
    // TRAILING_STOP / MOO / MOC / LOO / LOC / PEGGED not expressible
    // in the legacy Indian shape today. Return null so the UI can
    // disable those options on Indian brokers.
    default:
      return null
  }
}
