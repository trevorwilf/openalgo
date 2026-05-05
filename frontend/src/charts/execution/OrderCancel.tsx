// Phase 6 — cancel-from-chart confirmation modal.
//
// Triggered by:
//   * Right-click context menu on an open order line.
//   * `DEL` key when an order line is hovered/selected.
//
// Same two-step modal contract as OrderEntryHUD — Enter does NOT
// auto-confirm; ESC cancels; idempotency token issued at open.

import { useCallback, useEffect, useMemo, useState } from 'react'
import { Button } from '@/components/ui/button'

export interface CancelIntent {
  order_id: string
  idempotency_token: string
}

export interface OrderCancelProps {
  orderId: string
  symbol: string
  side: 'BUY' | 'SELL'
  qty: string
  price: string | null
  onConfirm(intent: CancelIntent): Promise<void> | void
  onDismiss(): void
  generateIdempotencyToken?: () => string
}

function defaultToken(): string {
  if (typeof globalThis.crypto?.randomUUID === 'function') {
    return globalThis.crypto.randomUUID()
  }
  return `tok-${Date.now().toString(36)}-${Math.random().toString(36).slice(2)}`
}

export function OrderCancel({
  orderId,
  symbol,
  side,
  qty,
  price,
  onConfirm,
  onDismiss,
  generateIdempotencyToken,
}: OrderCancelProps) {
  const tokenGen = generateIdempotencyToken ?? defaultToken
  const idempotencyToken = useMemo(() => tokenGen(), [tokenGen])
  const [submitting, setSubmitting] = useState(false)

  useEffect(() => {
    const handler = (e: KeyboardEvent) => {
      if (e.key === 'Escape') {
        e.preventDefault()
        onDismiss()
      }
      // Enter must NEVER auto-confirm.
      if (e.key === 'Enter') {
        e.preventDefault()
        e.stopPropagation()
      }
    }
    window.addEventListener('keydown', handler, true)
    return () => window.removeEventListener('keydown', handler, true)
  }, [onDismiss])

  const handle = useCallback(async () => {
    if (submitting) return
    setSubmitting(true)
    try {
      await onConfirm({ order_id: orderId, idempotency_token: idempotencyToken })
    } finally {
      setSubmitting(false)
    }
  }, [submitting, onConfirm, orderId, idempotencyToken])

  return (
    <div
      data-testid="order-cancel"
      className="fixed inset-0 z-40 flex items-center justify-center bg-black/40"
      role="dialog"
      aria-modal="true"
    >
      <div className="w-full max-w-sm rounded-md border bg-background p-4 shadow-lg">
        <h2 className="text-base font-medium">Cancel order</h2>
        <ul className="mt-2 space-y-1 rounded-sm border bg-card p-2 text-xs">
          <li>
            Order ID: <strong>{orderId}</strong>
          </li>
          <li>
            Symbol: <strong>{symbol}</strong>
          </li>
          <li>
            Side: <strong>{side}</strong>
          </li>
          <li>
            Quantity: <strong>{qty}</strong>
          </li>
          <li>
            Price: <strong>{price ?? 'MARKET'}</strong>
          </li>
        </ul>
        <p className="mt-2 text-xs text-muted-foreground">
          Press Confirm to cancel the order. Pressing Enter does NOT auto-confirm.
        </p>
        <div className="mt-3 flex justify-end gap-2">
          <Button
            type="button"
            variant="ghost"
            onClick={onDismiss}
            data-testid="order-cancel-dismiss"
          >
            Keep
          </Button>
          <Button
            type="button"
            variant="destructive"
            onClick={handle}
            disabled={submitting}
            data-testid="order-cancel-confirm"
          >
            {submitting ? '…' : 'Cancel order'}
          </Button>
        </div>
      </div>
    </div>
  )
}
