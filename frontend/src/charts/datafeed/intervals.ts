// Phase 1 — Datafeed Foundation
// Canonical interval enum + per-broker translation. Mirrors
// services/charts/intervals_service.py (note: different file from the
// pre-existing services/intervals_service.py which serves the v1 lane).

import { CANONICAL_INTERVALS, type CanonicalInterval } from '../types/interval'

export { CANONICAL_INTERVALS, type CanonicalInterval }

/**
 * Broker-specific interval aliases. Keys are the canonical token;
 * values are what the broker's BrokerData.timeframe_map expects.
 *
 * Sourced from broker/<code>/api/data.py timeframe_map at the time of
 * Phase 1; broker plugins remain the authoritative source.
 */
type BrokerName = 'zerodha' | 'alpaca'

const ZERODHA_MAP: Partial<Record<CanonicalInterval, string>> = {
  '1m': 'minute',
  '3m': '3minute',
  '5m': '5minute',
  '10m': '10minute',
  '15m': '15minute',
  '30m': '30minute',
  '1h': '60minute',
  '1d': 'day',
}

const ALPACA_MAP: Partial<Record<CanonicalInterval, string>> = {
  '1m': '1Min',
  '5m': '5Min',
  '15m': '15Min',
  '30m': '30Min',
  '1h': '1Hour',
  '1d': '1Day',
  '1w': '1Week',
  '1mo': '1Month',
}

/**
 * Translate a canonical interval to the broker's native timeframe token.
 * Returns null when the broker does not support the interval.
 */
export function translateForBroker(interval: CanonicalInterval, broker: BrokerName): string | null {
  const map = broker === 'zerodha' ? ZERODHA_MAP : broker === 'alpaca' ? ALPACA_MAP : null
  if (!map) return null
  return map[interval] ?? null
}

/** All canonical intervals a broker supports. */
export function supportedForBroker(broker: BrokerName): CanonicalInterval[] {
  return CANONICAL_INTERVALS.filter((i) => translateForBroker(i, broker) != null)
}
