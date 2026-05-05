// Phase 6 — strategy signal markers.
//
// Display-tree component. Renders flag / arrow markers on the chart
// based on /api/v2/strategy-signals events. Mounting is handled by
// the engine adapter via `addDrawing` in Phase 5+; Phase 6 surfaces
// the data layer + a list view for accessibility.

import type { StrategySignalOverlay } from '../types/overlays'

export interface StrategySignalLayerProps {
  signals: readonly StrategySignalOverlay[]
}

export function StrategySignalLayer({ signals }: StrategySignalLayerProps) {
  return (
    <div
      data-testid="strategy-signal-layer"
      data-count={signals.length}
      className="pointer-events-none absolute inset-x-0 top-0"
    >
      <ul className="flex flex-wrap gap-1 p-2 text-[10px]">
        {signals.map((s) => (
          <li
            key={s.id}
            data-testid={`signal-row-${s.id}`}
            data-kind={s.kind}
            className={
              s.kind === 'BUY'
                ? 'rounded-sm border border-green-500/60 bg-green-500/20 px-2 py-0.5 text-green-200'
                : s.kind === 'SELL'
                  ? 'rounded-sm border border-red-500/60 bg-red-500/20 px-2 py-0.5 text-red-200'
                  : s.kind === 'EXIT'
                    ? 'rounded-sm border border-yellow-500/60 bg-yellow-500/20 px-2 py-0.5 text-yellow-200'
                    : 'rounded-sm border bg-muted/60 px-2 py-0.5'
            }
          >
            {s.kind} · {s.symbol} · {s.source}
          </li>
        ))}
      </ul>
    </div>
  )
}
