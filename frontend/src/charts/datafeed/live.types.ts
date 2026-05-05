// Phase 1 + Phase 4 — types shared by the live datafeed module.
//
// Split out into a separate module so the Phase 4 implementation in
// `live.ts` can import the contract from a stable location while
// the body changes between phases.

import type { CanonicalInterval } from '../types/interval'
import type { NormalizedTick } from '../types/tick'
import type { InstrumentRefInput } from './historical'

export type TickHandler = (tick: NormalizedTick) => void

export interface SubscribeBarsArgs {
  ref: InstrumentRefInput
  interval: CanonicalInterval
  onTick: TickHandler
  /** Optional resume hook — Phase 4 sends this on (re)connect so the
   *  server backfills any missed bars from `last_seen_ts` to now. */
  resumeFromMs?: number
  /** Hint to use polling instead of websocket; defaults to websocket
   *  when the broker advertises streaming, polling otherwise (Q-15). */
  transportHint?: 'websocket' | 'polling'
  /** Polling interval in ms when transportHint=polling. Default 1000. */
  pollingIntervalMs?: number
}

export interface BarSubscription {
  subscription_id: string
  transport: 'websocket' | 'polling' | 'pending'
}
