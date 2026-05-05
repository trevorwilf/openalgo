// Phase 1 — Datafeed Foundation
// Live subscription shells. Final signature here so Phase 3 can wire
// engines against a stable contract; body becomes real in Phase 4.

import type { CanonicalInterval } from '../types/interval'
import type { NormalizedTick } from '../types/tick'
import type { InstrumentRefInput } from './historical'

export type TickHandler = (tick: NormalizedTick) => void

export interface SubscribeBarsArgs {
  ref: InstrumentRefInput
  interval: CanonicalInterval
  onTick: TickHandler
  /**
   * Optional UTC ms from which the server should backfill any missed
   * bars on (re)connect. Phase 4 wires this to the WS envelope's
   * `last_seen_ts` resume hook.
   */
  resumeFromMs?: number
}

export interface BarSubscription {
  /** Server-assigned subscription identifier (used to unsubscribe). */
  subscription_id: string
  /** Best-effort transport label for diagnostics. */
  transport: 'websocket' | 'polling' | 'pending'
}

/**
 * Subscribe to live bar updates for (ref, interval).
 *
 * TODO Phase 4 — opens the multiplexed /api/v2/streaming connection,
 * sends a `subscribe` envelope, and routes incoming tick / bar_update /
 * bar_close envelopes to `onTick`. Reconnect with backoff per
 * `RECONNECT_BACKOFF_MS`; heartbeat every `HEARTBEAT_INTERVAL_MS`.
 */
export async function subscribeBars(args: SubscribeBarsArgs): Promise<BarSubscription> {
  // Touch the args so the linter doesn't strip them; signature is the
  // contract Phase 4 implements against.
  void args
  return { subscription_id: '', transport: 'pending' }
}

/**
 * Unsubscribe from a previously created live subscription.
 *
 * TODO Phase 4 — sends an `unsubscribe` envelope; on success the server
 * stops fanning out ticks for this subscription. The client may still
 * receive in-flight bars until ack.
 */
export async function unsubscribeBars(sub: BarSubscription): Promise<void> {
  void sub
}
