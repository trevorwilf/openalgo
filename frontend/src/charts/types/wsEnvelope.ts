// Phase 1 — Datafeed Foundation
// WebSocket envelope contract per HANDOFF §0.5.
// Mirror of services/charts/ws_envelope.py.

import type { UTCMillis } from './interval'

export type EnvelopeType =
  | 'bar_update'
  | 'bar_close'
  | 'indicator_update'
  | 'order_update'
  | 'position_update'
  | 'trade_event'
  | 'strategy_signal'
  | 'ack'
  | 'error'

export interface WSEnvelope<P = unknown> {
  type: EnvelopeType
  /** Subscription identifier; may be empty for ack/error. */
  subscription_id: string
  /** UTC milliseconds — server-stamped envelope timestamp. */
  ts: UTCMillis
  payload: P
}

// Client → server control messages.
export interface WSSubscribe {
  op: 'subscribe'
  channel: string
  /** Optional resume hook — server backfills bars from this UTC-ms onward. */
  last_seen_ts?: UTCMillis
  params?: Record<string, unknown>
}

export interface WSUnsubscribe {
  op: 'unsubscribe'
  subscription_id: string
}

export interface WSHeartbeat {
  op: 'heartbeat'
  /** Client-side UTC ms — server echoes for RTT calc. */
  client_ts: UTCMillis
}

export type WSControl = WSSubscribe | WSUnsubscribe | WSHeartbeat

/** Heartbeat interval in ms — must match the server. */
export const HEARTBEAT_INTERVAL_MS = 30_000

/** Reconnect backoff schedule in ms (cap at 30s). */
export const RECONNECT_BACKOFF_MS = [500, 1000, 2000, 5000, 10000, 30000]
