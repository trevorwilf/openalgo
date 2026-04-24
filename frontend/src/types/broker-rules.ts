/**
 * Broker rule matrix types — mirrors the backend `domain.BrokerOrderRule`
 * (Phase 5). Consumed by the capability-native order ticket
 * (PlaceOrderDialogV2).
 */

import type { AssetClass, PlatformOrderType, PlatformQuantityUnit, PlatformSession, PlatformTimeInForce } from './capabilities'

export type OrderSide = 'BUY' | 'SELL'

export interface BrokerOrderRule {
  venue_code: string | null
  asset_class: AssetClass | null
  session: PlatformSession | null
  side: OrderSide | null
  quantity_unit: PlatformQuantityUnit | null
  allowed_order_types: PlatformOrderType[]
  allowed_time_in_force: PlatformTimeInForce[]
  allows_fractional: boolean
  allows_notional: boolean
  allows_short: boolean
  requires_limit_price: boolean
}

/** Count of non-null qualifier fields — higher is more specific. */
export function ruleSpecificity(rule: BrokerOrderRule): number {
  let score = 0
  if (rule.venue_code !== null) score++
  if (rule.asset_class !== null) score++
  if (rule.session !== null) score++
  if (rule.side !== null) score++
  if (rule.quantity_unit !== null) score++
  return score
}

/** Pick the most specific rule matching ``(venue, assetClass)``. */
export function pickMatchingRule(
  rules: BrokerOrderRule[],
  venueCode: string | null,
  assetClass: AssetClass | null,
): BrokerOrderRule | null {
  const matches = rules.filter((r) => {
    if (r.venue_code !== null && r.venue_code !== venueCode) return false
    if (r.asset_class !== null && r.asset_class !== assetClass) return false
    return true
  })
  if (matches.length === 0) return null
  matches.sort((a, b) => ruleSpecificity(b) - ruleSpecificity(a))
  return matches[0]
}
