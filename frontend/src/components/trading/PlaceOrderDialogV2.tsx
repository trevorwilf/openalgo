/**
 * PlaceOrderDialogV2 — capability-native order ticket for promoted
 * brokers. Reads /api/broker/capabilities + /api/broker/rules + an
 * instrument lookup, then renders only the controls the broker can
 * honor.
 *
 * Design intent:
 * - No Indian legacy concepts: no product-type selector (that's an
 *   IN_STOCK thing), no MIS/NRML/CNC, no SL/SL-M mapping.
 * - Quantity unit chosen from the intersection of
 *   `capabilities.supported_quantity_units`, broker rule
 *   allowlists, and the instrument's `supports_fractional`.
 * - Currency rendered via `Intl.NumberFormat` keyed on the instrument
 *   currency — never a hardcoded symbol map.
 * - Submits to /api/v2/orders with apikey in the body (compatible
 *   with the rest of v2).
 */

import { useEffect, useMemo, useState } from 'react'
import type { BrokerCapabilities, PlatformOrderType, PlatformQuantityUnit, PlatformTimeInForce } from '@/types/capabilities'
import type { BrokerOrderRule, OrderSide } from '@/types/broker-rules'
import { pickMatchingRule } from '@/types/broker-rules'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { cn } from '@/lib/utils'

export interface Instrument {
  instrument_id?: string | null
  venue_code: string
  canonical_symbol: string
  asset_class: 'EQUITY' | 'ETF' | 'FUTURE' | 'OPTION' | string
  currency: string
  lot_size?: number | null
  tick_size?: number | string | null
  supports_fractional?: boolean
}

interface PlaceOrderDialogV2Props {
  apikey: string
  capabilities: BrokerCapabilities
  rules: BrokerOrderRule[]
  instrument: Instrument
  onSubmit?: (payload: unknown, response: unknown) => void
  onError?: (error: unknown) => void
}

/** Build the list of quantity units the user can pick, honoring
 * capability, rule, and instrument constraints. */
function availableQuantityUnits(
  caps: BrokerCapabilities,
  rule: BrokerOrderRule | null,
  instrument: Instrument,
): PlatformQuantityUnit[] {
  const out: PlatformQuantityUnit[] = []
  const capUnits = new Set(caps.supported_quantity_units)
  if (capUnits.has('WHOLE')) out.push('WHOLE')

  const ruleAllowsFractional = rule ? rule.allows_fractional : true
  if (
    capUnits.has('FRACTIONAL')
    && caps.supports_fractional
    && ruleAllowsFractional
    && (instrument.supports_fractional !== false)
  ) {
    out.push('FRACTIONAL')
  }

  const ruleAllowsNotional = rule ? rule.allows_notional : true
  if (
    capUnits.has('NOTIONAL')
    && caps.supports_notional_orders
    && ruleAllowsNotional
  ) {
    out.push('NOTIONAL')
  }

  if (capUnits.has('CONTRACTS')) out.push('CONTRACTS')
  if (capUnits.has('LOTS')) out.push('LOTS')
  return out
}

function availableOrderTypes(
  caps: BrokerCapabilities,
  rule: BrokerOrderRule | null,
): PlatformOrderType[] {
  const fromRule = rule?.allowed_order_types ?? caps.supported_order_types
  const capSet = new Set(caps.supported_order_types)
  return fromRule.filter((t) => capSet.has(t))
}

function availableTimeInForce(
  caps: BrokerCapabilities,
  rule: BrokerOrderRule | null,
): PlatformTimeInForce[] {
  const fromRule = rule?.allowed_time_in_force ?? caps.supported_time_in_force
  const capSet = new Set(caps.supported_time_in_force)
  return fromRule.filter((t) => capSet.has(t))
}

/** Currency-aware formatter — no hardcoded symbol maps. */
export function formatCurrency(amount: number | string, currency: string): string {
  const n = typeof amount === 'string' ? Number(amount) : amount
  if (!Number.isFinite(n)) return String(amount)
  try {
    return new Intl.NumberFormat(undefined, {
      style: 'currency',
      currency,
      maximumFractionDigits: 6,
    }).format(n)
  } catch {
    return `${n} ${currency}`
  }
}

export function PlaceOrderDialogV2({
  apikey,
  capabilities,
  rules,
  instrument,
  onSubmit,
  onError,
}: PlaceOrderDialogV2Props) {
  const matchedRule = useMemo(
    () => pickMatchingRule(rules, instrument.venue_code, instrument.asset_class as never),
    [rules, instrument.venue_code, instrument.asset_class],
  )

  const qtyUnits = useMemo(
    () => availableQuantityUnits(capabilities, matchedRule, instrument),
    [capabilities, matchedRule, instrument],
  )
  const orderTypes = useMemo(
    () => availableOrderTypes(capabilities, matchedRule),
    [capabilities, matchedRule],
  )
  const tifs = useMemo(
    () => availableTimeInForce(capabilities, matchedRule),
    [capabilities, matchedRule],
  )

  const [side, setSide] = useState<OrderSide>('BUY')
  const [quantityUnit, setQuantityUnit] = useState<PlatformQuantityUnit>(qtyUnits[0] ?? 'WHOLE')
  const [orderType, setOrderType] = useState<PlatformOrderType>(orderTypes[0] ?? 'MARKET')
  const [timeInForce, setTimeInForce] = useState<PlatformTimeInForce>(tifs[0] ?? 'DAY')
  const [quantity, setQuantity] = useState<string>('1')
  const [price, setPrice] = useState<string>('')
  const [extendedHours, setExtendedHours] = useState(false)
  const [submitting, setSubmitting] = useState(false)

  // Keep the dropdown selection valid when rules change under us.
  useEffect(() => {
    if (!qtyUnits.includes(quantityUnit)) {
      setQuantityUnit(qtyUnits[0] ?? 'WHOLE')
    }
  }, [qtyUnits, quantityUnit])
  useEffect(() => {
    if (!orderTypes.includes(orderType)) {
      setOrderType(orderTypes[0] ?? 'MARKET')
    }
  }, [orderTypes, orderType])
  useEffect(() => {
    if (!tifs.includes(timeInForce)) {
      setTimeInForce(tifs[0] ?? 'DAY')
    }
  }, [tifs, timeInForce])

  const priceRequired = orderType === 'LIMIT' || orderType === 'STOP_LIMIT'
     || orderType === 'LIMIT_ON_OPEN' || orderType === 'LIMIT_ON_CLOSE'
  const showExtendedHoursToggle = capabilities.supports_extended_hours === true

  // Product-type selector is an Indian legacy concept. Never shown when
  // IN_STOCK is not in market_families.
  const showProductType = capabilities.market_families.includes('IN_STOCK')

  const submit = async (e: React.FormEvent) => {
    e.preventDefault()
    setSubmitting(true)
    try {
      // InstrumentRef accepts exactly one of:
      //   (instrument_id) | (venue_code + canonical_symbol) |
      //   (identifier_type + identifier_value)
      // Prefer instrument_id when present; otherwise fall back to the
      // venue + canonical pair. Sending all three at once is rejected
      // server-side with "got multiple".
      const instrumentRef = instrument.instrument_id
        ? { instrument_id: instrument.instrument_id }
        : {
            venue_code: instrument.venue_code,
            canonical_symbol: instrument.canonical_symbol,
          }
      const body: Record<string, unknown> = {
        apikey,
        instrument: instrumentRef,
        side,
        order_type: orderType,
        quantity,
        quantity_unit: quantityUnit,
        time_in_force: timeInForce,
      }
      if (priceRequired) {
        // NormalizedOrderRequest validates `price` as a Decimal. An
        // empty string fails parsing — only attach when the operator
        // entered something.
        if (price && price.trim() !== '') body.price = price
      }
      if (showExtendedHoursToggle) body.extended_hours = extendedHours
      const resp = await fetch('/api/v2/orders', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(body),
      })
      const json = await resp.json()
      if (!resp.ok) {
        if (onError) onError(json)
      } else if (onSubmit) {
        onSubmit(body, json)
      }
    } catch (err) {
      if (onError) onError(err)
    } finally {
      setSubmitting(false)
    }
  }

  // Native ``<select>`` styled with shadcn/Tailwind classes — the
  // hidden-but-accessible cousin of the shadcn ``Select`` component.
  // Keeps Playwright's ``selectOption()`` working (Radix Select is a
  // combobox built from divs/portals; ``selectOption`` doesn't drive
  // it) while still matching the rest of the UI's design language.
  const selectClass = cn(
    'flex h-9 w-full rounded-md border border-input bg-transparent px-3 py-1 text-sm',
    'shadow-xs transition-[color,box-shadow] outline-none',
    'focus-visible:border-ring focus-visible:ring-ring/50 focus-visible:ring-[3px]',
    'disabled:pointer-events-none disabled:cursor-not-allowed disabled:opacity-50',
  )

  return (
    <form onSubmit={submit} className="space-y-4 pt-2" data-testid="place-order-v2">
      {/* Symbol header — prominent, read-only context */}
      <div className="rounded-md border bg-muted/30 px-3 py-2">
        <div className="text-xs uppercase tracking-wide text-muted-foreground">
          Trading
        </div>
        <div
          id="v2-symbol"
          data-testid="v2-symbol"
          className="font-mono text-base font-semibold"
        >
          {instrument.canonical_symbol}{' '}
          <span className="text-muted-foreground font-normal">
            @ {instrument.venue_code}
          </span>
        </div>
      </div>

      {/* Buy / Sell toggle — two big colour-coded buttons rather than a
          dropdown. Native <select> still under the hood (data-testid
          preserved + hidden) so Playwright's selectOption keeps
          working without rewriting the test suite. */}
      <div className="space-y-1.5">
        <Label htmlFor="v2-side">Action</Label>
        <select
          id="v2-side"
          value={side}
          onChange={(e) => setSide(e.target.value as OrderSide)}
          data-testid="v2-side"
          className="sr-only"
          aria-label="Buy or sell"
        >
          <option value="BUY">Buy</option>
          <option value="SELL">Sell</option>
        </select>
        <div className="grid grid-cols-2 gap-2">
          <Button
            type="button"
            variant={side === 'BUY' ? 'default' : 'outline'}
            onClick={() => setSide('BUY')}
            className={cn(
              'h-10 font-semibold',
              side === 'BUY' && 'bg-green-600 hover:bg-green-700 text-white',
            )}
            data-testid="v2-side-buy"
          >
            Buy
          </Button>
          <Button
            type="button"
            variant={side === 'SELL' ? 'default' : 'outline'}
            onClick={() => setSide('SELL')}
            className={cn(
              'h-10 font-semibold',
              side === 'SELL' && 'bg-red-600 hover:bg-red-700 text-white',
            )}
            data-testid="v2-side-sell"
          >
            Sell
          </Button>
        </div>
      </div>

      {/* Quantity row — unit + amount side-by-side */}
      <div className="grid grid-cols-[1fr_2fr] gap-2">
        <div className="space-y-1.5">
          <Label htmlFor="v2-quantity-unit">Unit</Label>
          <select
            id="v2-quantity-unit"
            value={quantityUnit}
            onChange={(e) => setQuantityUnit(e.target.value as PlatformQuantityUnit)}
            data-testid="v2-quantity-unit"
            className={selectClass}
          >
            {qtyUnits.map((u) => (
              <option key={u} value={u}>
                {u}
              </option>
            ))}
          </select>
        </div>
        <div className="space-y-1.5">
          <Label htmlFor="v2-quantity">Quantity</Label>
          <Input
            id="v2-quantity"
            value={quantity}
            onChange={(e) => setQuantity(e.target.value)}
            data-testid="v2-quantity"
            inputMode="decimal"
            placeholder={quantityUnit === 'NOTIONAL' ? '100.00' : '1'}
          />
        </div>
      </div>
      <div
        data-testid="v2-quantity-formatted"
        className="-mt-2 text-xs text-muted-foreground"
      >
        {quantityUnit === 'NOTIONAL'
          ? `≈ ${formatCurrency(quantity, instrument.currency)} of ${instrument.canonical_symbol}`
          : `${quantity} ${instrument.canonical_symbol} share${quantity === '1' ? '' : 's'}`}
      </div>

      {/* Order type + Limit price (when applicable) */}
      <div
        className={cn(
          'grid gap-2',
          priceRequired ? 'grid-cols-2' : 'grid-cols-1',
        )}
      >
        <div className="space-y-1.5">
          <Label htmlFor="v2-order-type">Order Type</Label>
          <select
            id="v2-order-type"
            value={orderType}
            onChange={(e) => setOrderType(e.target.value as PlatformOrderType)}
            data-testid="v2-order-type"
            className={selectClass}
          >
            {orderTypes.map((t) => (
              <option key={t} value={t}>
                {t}
              </option>
            ))}
          </select>
        </div>
        {priceRequired && (
          <div className="space-y-1.5">
            <Label htmlFor="v2-price">
              Limit Price ({instrument.currency})
            </Label>
            <Input
              id="v2-price"
              value={price}
              onChange={(e) => setPrice(e.target.value)}
              data-testid="v2-price"
              inputMode="decimal"
              placeholder="100.00"
            />
          </div>
        )}
      </div>

      {/* Time in force + Extended hours */}
      <div className="grid grid-cols-2 gap-2 items-end">
        <div className="space-y-1.5">
          <Label htmlFor="v2-tif">Time in Force</Label>
          <select
            id="v2-tif"
            value={timeInForce}
            onChange={(e) => setTimeInForce(e.target.value as PlatformTimeInForce)}
            data-testid="v2-tif"
            className={selectClass}
          >
            {tifs.map((t) => (
              <option key={t} value={t}>
                {t}
              </option>
            ))}
          </select>
        </div>
        {showExtendedHoursToggle ? (
          <label
            htmlFor="v2-extended-hours"
            className="flex items-center gap-2 h-9 px-3 rounded-md border bg-muted/20 cursor-pointer text-sm font-medium"
          >
            <input
              id="v2-extended-hours"
              type="checkbox"
              checked={extendedHours}
              onChange={(e) => setExtendedHours(e.target.checked)}
              data-testid="v2-extended-hours"
              className="h-4 w-4 rounded border-input accent-primary"
            />
            Extended hours
          </label>
        ) : (
          <div />
        )}
      </div>

      {/* Product type is Indian-legacy only — never shown for
          non-IN_STOCK brokers. The absence of the selector is part
          of the contract and is asserted by the test suite. */}
      {showProductType && (
        <div data-testid="v2-product-type-present" className="hidden">
          product type selector
        </div>
      )}

      <Button
        type="submit"
        disabled={submitting}
        data-testid="v2-submit"
        className={cn(
          'w-full h-11 font-semibold',
          side === 'BUY'
            ? 'bg-green-600 hover:bg-green-700 text-white'
            : 'bg-red-600 hover:bg-red-700 text-white',
        )}
      >
        {submitting
          ? 'Submitting…'
          : `${side === 'BUY' ? 'Buy' : 'Sell'} ${instrument.canonical_symbol}`}
      </Button>
    </form>
  )
}

export default PlaceOrderDialogV2
