// Phase 6 — chart overlay schemas (Appendix B §10.2-10.5).
//
// All shapes live at the wire layer in the OpenAlgo decimal-string
// convention. The display-tree components round-trip these directly
// from /api/v2/orders, /api/v2/positions, /api/v2/trades, and
// /api/v2/strategy-signals.

export interface OrderOverlay {
  /** Stable broker order id. */
  order_id: string
  symbol: string
  side: 'BUY' | 'SELL'
  /** OpenAlgo product code. */
  product?: string | null
  /** Order type per BrokerCapabilities.platform_order_types. */
  order_type: string
  qty: string
  /** LIMIT/STOP price; null for MARKET. */
  price: string | null
  /** Trigger price for STOP variants. */
  trigger_price?: string | null
  status: 'PENDING' | 'OPEN' | 'PARTIAL' | 'FILLED' | 'CANCELLED' | 'REJECTED'
  /** UTC seconds. */
  ts: number
}

export interface PositionOverlay {
  symbol: string
  qty: string
  avg_price: string
  /** Realized + unrealized aggregate; sign convention: positive
   *  = profit. */
  pnl?: string | null
}

export interface FillOverlay {
  fill_id: string
  order_id: string
  symbol: string
  side: 'BUY' | 'SELL'
  qty: string
  price: string
  /** UTC seconds. */
  ts: number
}

export interface StrategySignalOverlay {
  id: number
  symbol: string
  kind: 'BUY' | 'SELL' | 'EXIT' | 'INFO'
  /** UTC seconds. */
  ts: number
  source: string
  payload?: Record<string, unknown>
}
