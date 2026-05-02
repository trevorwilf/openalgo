// AdminIndex / FreezeQty / MarketTimings were relocated to
// src/india_legacy/pages/admin/ in v9-bis (India-only admin pages).
// Holidays remains at src/pages/admin/ (region-neutral).
export { default as AdminIndex } from '@/india_legacy/pages/admin/AdminIndex'
export { default as FreezeQty } from '@/india_legacy/pages/admin/FreezeQty'
export { default as MarketTimings } from '@/india_legacy/pages/admin/MarketTimings'
export { default as Holidays } from './Holidays'
