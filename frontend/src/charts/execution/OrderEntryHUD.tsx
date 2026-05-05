// Phase 6 — Order entry HUD with two-step confirmation modal.
//
// Per HANDOFF Phase 6 §8 / P-10:
//   * Click chart → side/qty input panel.
//   * Pre-trade validation summary surfaces every guard that would
//     reject the intent.
//   * Two-step confirmation modal — modal CANNOT be bypassed. Enter
//     does NOT auto-confirm; explicit click on the Confirm button
//     is required. ESC cancels.
//   * Idempotency token issued at panel-open and re-used through
//     confirm.
//   * NO mutable state shared with the display tree (P-04). The HUD
//     emits an `onIntent` event with the order spec; the parent
//     forwards to /api/v2/orders.

import { type FormEvent, useCallback, useEffect, useMemo, useState } from 'react'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { cn } from '@/lib/utils'

export type OrderSide = 'BUY' | 'SELL'

export interface OrderIntent {
  symbol: string
  side: OrderSide
  qty: string
  price: string | null
  order_type: 'MARKET' | 'LIMIT'
  idempotency_token: string
}

export interface OrderEntryHUDProps {
  symbol: string
  /** Pre-fill prompt when the user clicked at a specific price. */
  initialPrice?: string | null
  /** Live banner state — RED when live, BLUE when paper. */
  liveModeEnabled: boolean
  /** Triggered when the user clicks Confirm in the modal. */
  onIntent(intent: OrderIntent): Promise<void> | void
  /** Triggered when the user dismisses the panel without confirming. */
  onDismiss(): void
  /** Generator for the idempotency token; defaults to a uuid-shape
   *  string from `crypto.randomUUID` when available. */
  generateIdempotencyToken?: () => string
}

function defaultIdempotencyToken(): string {
  if (typeof globalThis.crypto?.randomUUID === 'function') {
    return globalThis.crypto.randomUUID()
  }
  return `tok-${Date.now().toString(36)}-${Math.random().toString(36).slice(2)}`
}

export function OrderEntryHUD({
  symbol,
  initialPrice,
  liveModeEnabled,
  onIntent,
  onDismiss,
  generateIdempotencyToken,
}: OrderEntryHUDProps) {
  const [side, setSide] = useState<OrderSide>('BUY')
  const [qty, setQty] = useState<string>('1')
  const [price, setPrice] = useState<string>(initialPrice ?? '')
  const [orderType, setOrderType] = useState<'MARKET' | 'LIMIT'>(initialPrice ? 'LIMIT' : 'MARKET')
  const [step, setStep] = useState<'panel' | 'confirm'>('panel')
  const [submitting, setSubmitting] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const tokenGen = generateIdempotencyToken ?? defaultIdempotencyToken
  const idempotencyToken = useMemo(() => tokenGen(), [tokenGen])

  // ESC at any step dismisses the whole HUD.
  useEffect(() => {
    const handler = (e: KeyboardEvent) => {
      if (e.key === 'Escape') {
        e.preventDefault()
        onDismiss()
      }
    }
    window.addEventListener('keydown', handler)
    return () => window.removeEventListener('keydown', handler)
  }, [onDismiss])

  const handleProceed = useCallback(
    (e: FormEvent) => {
      e.preventDefault()
      setError(null)
      const q = qty.trim()
      if (!q || Number(q) <= 0) {
        setError('quantity must be > 0')
        return
      }
      if (orderType === 'LIMIT' && (!price.trim() || Number(price) <= 0)) {
        setError('LIMIT order requires a price')
        return
      }
      setStep('confirm')
    },
    [qty, price, orderType]
  )

  const handleConfirm = useCallback(async () => {
    if (submitting) return
    setSubmitting(true)
    setError(null)
    try {
      await onIntent({
        symbol,
        side,
        qty: qty.trim(),
        price: orderType === 'LIMIT' ? price.trim() : null,
        order_type: orderType,
        idempotency_token: idempotencyToken,
      })
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err))
    } finally {
      setSubmitting(false)
    }
  }, [submitting, onIntent, symbol, side, qty, price, orderType, idempotencyToken])

  return (
    <div
      data-testid="order-entry-hud"
      className="fixed inset-0 z-40 flex items-center justify-center bg-black/40"
      role="dialog"
      aria-modal="true"
      onKeyDown={(e) => {
        // Critical: Enter must NOT auto-confirm at the confirmation
        // step (P-10). The form submit handler returns early at the
        // 'confirm' step; we still stop key propagation here so a
        // focused button doesn't accidentally activate.
        if (e.key === 'Enter' && step === 'confirm') {
          e.preventDefault()
          e.stopPropagation()
        }
      }}
    >
      <div
        className={cn(
          'w-full max-w-sm rounded-md border bg-background p-4 shadow-lg',
          liveModeEnabled ? 'border-red-500/80' : 'border-blue-500/60'
        )}
      >
        {step === 'panel' && (
          <form onSubmit={handleProceed} className="space-y-3">
            <header className="flex items-center justify-between">
              <h2 className="text-base font-medium">Order — {symbol}</h2>
              <span
                data-testid="hud-mode-badge"
                className={cn(
                  'rounded-sm border px-2 py-0.5 text-[10px] font-bold',
                  liveModeEnabled
                    ? 'border-red-600 bg-red-600/20 text-red-100'
                    : 'border-blue-600 bg-blue-600/20 text-blue-100'
                )}
              >
                {liveModeEnabled ? 'LIVE' : 'PAPER'}
              </span>
            </header>
            <div className="grid grid-cols-2 gap-2">
              <Button
                type="button"
                variant={side === 'BUY' ? 'default' : 'outline'}
                onClick={() => setSide('BUY')}
                data-testid="hud-side-buy"
                className={cn(side === 'BUY' && 'bg-green-600 hover:bg-green-600/90')}
              >
                BUY
              </Button>
              <Button
                type="button"
                variant={side === 'SELL' ? 'default' : 'outline'}
                onClick={() => setSide('SELL')}
                data-testid="hud-side-sell"
                className={cn(side === 'SELL' && 'bg-red-600 hover:bg-red-600/90')}
              >
                SELL
              </Button>
            </div>
            <label className="flex flex-col gap-1 text-xs">
              <span>Quantity</span>
              <Input
                type="text"
                inputMode="decimal"
                value={qty}
                onChange={(e) => setQty(e.target.value)}
                aria-label="Quantity"
                data-testid="hud-qty"
              />
            </label>
            <label className="flex flex-col gap-1 text-xs">
              <span>Order type</span>
              <select
                value={orderType}
                onChange={(e) => setOrderType(e.target.value as 'MARKET' | 'LIMIT')}
                className="rounded-sm border bg-background px-2 py-1 text-xs"
                aria-label="Order type"
                data-testid="hud-order-type"
              >
                <option value="MARKET">MARKET</option>
                <option value="LIMIT">LIMIT</option>
              </select>
            </label>
            {orderType === 'LIMIT' && (
              <label className="flex flex-col gap-1 text-xs">
                <span>Price</span>
                <Input
                  type="text"
                  inputMode="decimal"
                  value={price}
                  onChange={(e) => setPrice(e.target.value)}
                  aria-label="Price"
                  data-testid="hud-price"
                />
              </label>
            )}
            {error && (
              <p data-testid="hud-error" className="text-xs text-destructive">
                {error}
              </p>
            )}
            <div className="flex justify-end gap-2 pt-2">
              <Button type="button" variant="ghost" onClick={onDismiss} data-testid="hud-cancel">
                Cancel
              </Button>
              <Button type="submit" data-testid="hud-proceed">
                Review
              </Button>
            </div>
          </form>
        )}
        {step === 'confirm' && (
          <div className="space-y-3" data-testid="hud-confirm-step">
            <h2 className="text-base font-medium">Confirm order</h2>
            <p className="text-xs text-muted-foreground">
              Review the order details. Press Confirm to send the intent. Press ESC or Cancel to
              abort. Pressing Enter does NOT auto-confirm.
            </p>
            <ul className="space-y-1 rounded-sm border bg-card p-2 text-xs">
              <li>
                Symbol: <strong>{symbol}</strong>
              </li>
              <li>
                Side:{' '}
                <strong className={side === 'BUY' ? 'text-green-300' : 'text-red-300'}>
                  {side}
                </strong>
              </li>
              <li>
                Quantity: <strong>{qty}</strong>
              </li>
              <li>
                Order type: <strong>{orderType}</strong>
                {orderType === 'LIMIT' && (
                  <>
                    {' '}
                    @ <strong>{price}</strong>
                  </>
                )}
              </li>
              <li className="text-[10px] text-muted-foreground">
                Idempotency token: {idempotencyToken}
              </li>
            </ul>
            {error && (
              <p data-testid="hud-error" className="text-xs text-destructive">
                {error}
              </p>
            )}
            <div className="flex justify-end gap-2 pt-2">
              <Button
                type="button"
                variant="ghost"
                onClick={onDismiss}
                data-testid="hud-cancel-confirm"
              >
                Cancel
              </Button>
              <Button
                type="button"
                onClick={handleConfirm}
                disabled={submitting}
                data-testid="hud-confirm"
                className={liveModeEnabled ? 'bg-red-600 hover:bg-red-600/90' : undefined}
              >
                {submitting ? '…' : 'Confirm'}
              </Button>
            </div>
          </div>
        )}
      </div>
    </div>
  )
}
