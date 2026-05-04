/**
 * v7 Phase 5 — region-aware content router.
 *
 * Renders different children based on the active broker's region.
 * Pages that need region-specific UI (e.g. dashboard tiles, P&L
 * formatters, regulatory disclosures) wrap their content in this
 * component and provide per-region children.
 *
 * The default ``children`` prop is rendered for ``india`` (the
 * legacy India lane). Region-specific overrides are passed via
 * the optional ``us`` / ``eu`` / ``uk`` props.
 *
 * Example:
 *
 *     <RegionContent
 *       us={<USOnlyDashboardTile />}
 *       eu={<EUOnlyDashboardTile />}
 *     >
 *       <IndiaDashboardTile />
 *     </RegionContent>
 *
 * When ``capabilities`` haven't loaded yet, renders the
 * ``loading`` slot (default: ``null`` — caller can supply a
 * skeleton).
 */

import type { ReactNode } from 'react'

import { type BrokerRegion, useBrokerRegion } from '@/hooks/useBrokerRegion'

export interface RegionContentProps {
  /** India sibling (default — also rendered for ``unknown`` until
   * a future operator setting overrides this). */
  children?: ReactNode
  us?: ReactNode
  eu?: ReactNode
  uk?: ReactNode
  /** Slot rendered while capabilities are loading. Defaults to
   * ``null`` so the page doesn't flash an empty state. */
  loading?: ReactNode
}

export function RegionContent({
  children,
  us,
  eu,
  uk,
  loading,
}: RegionContentProps) {
  const region = useBrokerRegion()

  if (region === 'unknown') return <>{loading ?? null}</>
  if (region === 'us' && us !== undefined) return <>{us}</>
  if (region === 'eu' && eu !== undefined) return <>{eu}</>
  if (region === 'uk' && uk !== undefined) return <>{uk}</>
  return <>{children ?? null}</>
}

/** Programmatic counterpart for callers that need to switch on
 * region inside a hook chain rather than via JSX. */
export function pickRegionValue<T>(
  region: BrokerRegion,
  values: { india?: T; us?: T; eu?: T; uk?: T; default?: T },
): T | undefined {
  if (region === 'india' && values.india !== undefined) return values.india
  if (region === 'us' && values.us !== undefined) return values.us
  if (region === 'eu' && values.eu !== undefined) return values.eu
  if (region === 'uk' && values.uk !== undefined) return values.uk
  return values.default
}
