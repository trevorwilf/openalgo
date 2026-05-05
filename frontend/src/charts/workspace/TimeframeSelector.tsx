// Phase 3 — per-cell timeframe selector, broker-capability filtered.
//
// `BrokerCapabilities.supported_intervals` lists the canonical
// intervals the active broker supports. When the field is missing or
// empty, we fall back to the full canonical vocabulary (every
// interval enabled) — same conservative default as Phase 1's
// `intervals_service.translate_for_broker` returning null.

import { useBrokerStore } from '@/stores/brokerStore'
import { selectActiveTab, useWorkspaceStore } from '../state/workspaceStore'
import { CANONICAL_INTERVALS, type CanonicalInterval, isCanonicalInterval } from '../types/interval'

const INTERVAL_LABEL: Record<CanonicalInterval, string> = {
  '1s': '1 sec',
  '5s': '5 sec',
  '15s': '15 sec',
  '30s': '30 sec',
  '1m': '1 min',
  '2m': '2 min',
  '3m': '3 min',
  '5m': '5 min',
  '10m': '10 min',
  '15m': '15 min',
  '30m': '30 min',
  '1h': '1 hour',
  '2h': '2 hour',
  '4h': '4 hour',
  '1d': '1 day',
  '1w': '1 week',
  '1mo': '1 month',
}

export interface TimeframeSelectorProps {
  cellId: string
  className?: string
  /** Test seam — overrides broker capability lookup. */
  supportedIntervals?: CanonicalInterval[]
}

export function TimeframeSelector({
  cellId,
  className,
  supportedIntervals,
}: TimeframeSelectorProps) {
  const activeTab = useWorkspaceStore(selectActiveTab)
  const setCellTimeframe = useWorkspaceStore((s) => s.setCellTimeframe)
  const capabilities = useBrokerStore((s) => s.capabilities)

  if (!activeTab) return null
  const cell = activeTab.cells.find((c) => c.id === cellId)
  if (!cell) return null

  const supported = (supportedIntervals ??
    readSupportedIntervals(capabilities)) as CanonicalInterval[]
  const list = supported.length > 0 ? supported : CANONICAL_INTERVALS

  return (
    <select
      data-testid={`timeframe-select-${cellId}`}
      value={cell.timeframe}
      onChange={(e) => {
        const v = e.target.value
        if (isCanonicalInterval(v)) {
          setCellTimeframe(activeTab.id, cellId, v)
        }
      }}
      className={className ?? 'rounded-sm border bg-background px-2 py-1 text-xs'}
      aria-label="Timeframe"
    >
      {(list as readonly string[]).map((iv) =>
        isCanonicalInterval(iv) ? (
          <option key={iv} value={iv}>
            {INTERVAL_LABEL[iv]}
          </option>
        ) : null
      )}
    </select>
  )
}

/** Read `supported_intervals` from BrokerCapabilities; tolerant to
 *  missing fields in older capability payloads. */
function readSupportedIntervals(caps: unknown): CanonicalInterval[] {
  if (!caps || typeof caps !== 'object') return []
  const v = (caps as Record<string, unknown>).supported_intervals
  if (!Array.isArray(v)) return []
  const out: CanonicalInterval[] = []
  for (const item of v) {
    if (typeof item === 'string' && isCanonicalInterval(item)) out.push(item)
  }
  return out
}
