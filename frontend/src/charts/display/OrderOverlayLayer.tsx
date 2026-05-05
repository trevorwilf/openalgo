// Phase 6 — read-only overlay of orders, positions, fills.
//
// P-04: this component lives in the display tree. It NEVER mutates
// store state and never emits an order intent. Real-time updates
// arrive via the /charts/streaming SocketIO namespace; the parent
// passes them in as props so the component is hermetic.

import type { FillOverlay, OrderOverlay, PositionOverlay } from '../types/overlays'

export interface OrderOverlayLayerProps {
  orders: readonly OrderOverlay[]
  positions: readonly PositionOverlay[]
  fills: readonly FillOverlay[]
}

export function OrderOverlayLayer({ orders, positions, fills }: OrderOverlayLayerProps) {
  return (
    <div
      data-testid="order-overlay-layer"
      data-orders={orders.length}
      data-positions={positions.length}
      data-fills={fills.length}
      className="pointer-events-none absolute inset-0"
    >
      <ul className="absolute right-2 top-2 space-y-1 text-[10px] pointer-events-auto">
        {orders.map((o) => (
          <li
            key={o.order_id}
            data-testid={`order-row-${o.order_id}`}
            className={
              o.side === 'BUY'
                ? 'rounded-sm border border-green-500/60 bg-green-500/10 px-2 py-0.5 text-green-200'
                : 'rounded-sm border border-red-500/60 bg-red-500/10 px-2 py-0.5 text-red-200'
            }
            title={`${o.side} ${o.qty} @ ${o.price ?? 'MKT'} (${o.status})`}
          >
            {o.side} {o.qty}
            {o.price ? ` @ ${o.price}` : ' @ MKT'}
          </li>
        ))}
      </ul>
      <ul className="absolute left-2 top-2 space-y-1 text-[10px]">
        {positions.map((p) => (
          <li
            key={p.symbol}
            data-testid={`position-row-${p.symbol}`}
            className="rounded-sm border bg-card/80 px-2 py-0.5"
          >
            {p.symbol}: {p.qty} @ {p.avg_price}
          </li>
        ))}
      </ul>
      <ul className="absolute bottom-2 right-2 space-y-1 text-[10px]">
        {fills.slice(-5).map((f) => (
          <li
            key={f.fill_id}
            data-testid={`fill-row-${f.fill_id}`}
            className="rounded-sm border bg-muted/60 px-2 py-0.5"
          >
            {f.side} {f.qty} @ {f.price}
          </li>
        ))}
      </ul>
    </div>
  )
}
