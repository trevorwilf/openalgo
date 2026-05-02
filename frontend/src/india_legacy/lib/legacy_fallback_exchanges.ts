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

// Phase 2 v4 (ADR 0023, invariant 1) renamed `LEGACY_FALLBACK_EXCHANGES`
// to `INDIA_LEGACY_FALLBACK_EXCHANGES`.
//
// v5 Phase 2 (Phase 6-bis closure): the deprecated alias has been
// removed per `docs/refactor/deprecation-schedule.md`. Direct callers
// must import the canonical name.

export const INDIA_LEGACY_FALLBACK_EXCHANGES: ReadonlyArray<string> = [
  'NSE',
  'BSE',
  'NFO',
  'BFO',
  'CDS',
  'MCX',
  'CRYPTO',
] as const

// v5 Phase 2 — fail-closed runtime guard.
//
// `assertIndiaContext` is called by hooks that legitimately consume
// `INDIA_LEGACY_FALLBACK_EXCHANGES` (today: only `useSupportedExchanges`
// when the active broker's `supported_regions` includes "india"). If a
// non-India region (or unknown region without an India shape) reaches
// this branch, the guard throws so the bug surfaces immediately
// instead of silently rendering NSE/BSE in a non-India UI.
//
// The guard is a function, not a side-effect at module load, because
// the literal list is also read by serialization tests that run
// without a broker context. Test fixtures bypass the guard by simply
// not calling it.
export class LegacyIndiaFallbackUsedOutsideIndia extends Error {
  constructor(activeRegion: string | null | undefined) {
    super(
      `INDIA_LEGACY_FALLBACK_EXCHANGES used in non-India region (active: ${
        activeRegion ?? 'unknown'
      }). v5 invariant: promoted code must not synthesize India defaults.`,
    )
    this.name = 'LegacyIndiaFallbackUsedOutsideIndia'
  }
}

export function assertIndiaContext(activeRegion: string | null | undefined): void {
  const r = (activeRegion ?? '').toLowerCase()
  if (r !== 'india') {
    throw new LegacyIndiaFallbackUsedOutsideIndia(activeRegion)
  }
}
