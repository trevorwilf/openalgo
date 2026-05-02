// components/trading/index.ts
// Barrel export for trading components.
//
// QuoteHeader and PlaceOrderDialog were relocated to
// src/india_legacy/components/trading/ in v9-bis (India-flavored
// option/quote UIs). MarketDepthPanel remains at
// src/components/trading/ (region-neutral depth ladder).

export { QuoteHeader } from '@/india_legacy/components/trading/QuoteHeader'
export type { QuoteHeaderProps } from '@/india_legacy/components/trading/QuoteHeader'

export { MarketDepthPanel } from './MarketDepthPanel'
export type { MarketDepthPanelProps, DepthLevel } from './MarketDepthPanel'

export { PlaceOrderDialog } from '@/india_legacy/components/trading/PlaceOrderDialog'
export type { PlaceOrderDialogProps } from '@/india_legacy/components/trading/PlaceOrderDialog'
