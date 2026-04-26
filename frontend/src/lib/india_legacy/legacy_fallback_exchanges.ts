// LEGACY INDIA COMPATIBILITY — last-resort exchange fallback used by
// useSupportedExchanges when capability fetch fails AND the active
// broker is India-shaped. Kept in this dedicated file so the literal
// list does NOT live in promoted/core hook code; the frontend literal
// scanner allowlists only this path.
//
// New code MUST NOT import this constant. Capability-driven exchange
// lists come from the BrokerCapabilities object exposed by the broker
// store. ADR 0017 formalizes the legacy stamp.
//
// frontend literal allowlist entry:
//   frontend/scripts/literal_scan_allowlist.json
//   { "path": "src/lib/india_legacy/legacy_fallback_exchanges.ts" }

export const LEGACY_FALLBACK_EXCHANGES: ReadonlyArray<string> = [
  'NSE',
  'BSE',
  'NFO',
  'BFO',
  'CDS',
  'MCX',
  'CRYPTO',
] as const
