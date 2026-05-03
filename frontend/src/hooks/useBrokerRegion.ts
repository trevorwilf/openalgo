/**
 * Resolve which market region the active broker plugin serves.
 *
 * Reads ``capabilities.supported_regions`` (loaded once into the
 * brokerStore at app boot). Returns the first declared region for
 * single-region plugins, or ``"india"`` when the plugin is
 * legacy-shaped (no ``supported_regions`` declared — preserves the
 * fail-open behavior the rest of the legacy India UI depends on).
 *
 * Pages that gate behavior on region call this hook and use the
 * result to either render their region-specific UI or show the
 * shared :class:`IndiaOnlyFeature` empty state.
 */

import { useBrokerStore } from '@/stores/brokerStore'

export type BrokerRegion = 'india' | 'us' | 'eu' | 'uk' | 'unknown'

/** Lower-cased region from capabilities, or ``"india"`` for legacy
 *  plugins that pre-date the ``supported_regions`` field. ``"unknown"``
 *  when capabilities aren't loaded yet (caller should render a
 *  loading state).
 */
export function useBrokerRegion(): BrokerRegion {
  const capabilities = useBrokerStore((s) => s.capabilities)
  const isLoaded = useBrokerStore((s) => s.isLoaded)

  if (!isLoaded || !capabilities) return 'unknown'

  const regions = (capabilities.supported_regions ?? []).map((r) =>
    String(r).toLowerCase(),
  )
  if (regions.length === 0) {
    // Legacy India plugin shape — no ``supported_regions`` declared.
    return 'india'
  }
  if (regions.includes('india')) return 'india'
  if (regions.includes('us')) return 'us'
  if (regions.includes('eu')) return 'eu'
  if (regions.includes('uk')) return 'uk'
  return 'unknown'
}

/** Convenience: ``true`` when the active broker serves the Indian
 *  exchanges (NSE/BSE/NFO/BFO/MCX/CDS). Used by feature-gating
 *  components to short-circuit India-specific UI.
 */
export function useIsIndiaBroker(): boolean {
  return useBrokerRegion() === 'india'
}
