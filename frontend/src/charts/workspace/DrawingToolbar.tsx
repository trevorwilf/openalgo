// Phase 5 — drawing toolbar.
//
// Surfaces the 9 drawing kinds from the OpenAlgo schema. The active
// drawing tool is held in local state; the actual mount of the
// drawing primitive happens inside each engine adapter (Lightweight
// uses Series Primitives; KLineChart Pro uses native overlays). The
// toolbar emits an `onPickKind` event so the parent (ChartCell or
// workspace) can wire the engine adapter when Phase 5+ engine work
// lands.

import { ArrowRight, Circle, Minus, MoveDiagonal, PencilLine, Square, Type } from 'lucide-react'
import { useState } from 'react'
import { Button } from '@/components/ui/button'
import { cn } from '@/lib/utils'
import { DRAWING_KINDS, type DrawingShape } from '../engine/drawings_translator'

const ICONS: Record<DrawingShape['kind'], typeof Minus> = {
  trendline: PencilLine,
  horizontal: Minus,
  vertical: Minus,
  ray: ArrowRight,
  rectangle: Square,
  ellipse: Circle,
  fib_retracement: MoveDiagonal,
  fib_extension: MoveDiagonal,
  text: Type,
}

const LABEL: Record<DrawingShape['kind'], string> = {
  trendline: 'Trendline',
  horizontal: 'Horizontal',
  vertical: 'Vertical',
  ray: 'Ray',
  rectangle: 'Rectangle',
  ellipse: 'Ellipse',
  fib_retracement: 'Fib Retracement',
  fib_extension: 'Fib Extension',
  text: 'Text',
}

export interface DrawingToolbarProps {
  onPickKind?(kind: DrawingShape['kind'] | null): void
  className?: string
}

export function DrawingToolbar({ onPickKind, className }: DrawingToolbarProps) {
  const [active, setActive] = useState<DrawingShape['kind'] | null>(null)
  const handle = (kind: DrawingShape['kind']) => {
    const next = active === kind ? null : kind
    setActive(next)
    onPickKind?.(next)
  }
  return (
    <div
      data-testid="drawing-toolbar"
      className={cn(
        'flex items-center gap-1 rounded-sm border bg-card/80 p-1 text-muted-foreground',
        className
      )}
    >
      {DRAWING_KINDS.map((kind) => {
        const Icon = ICONS[kind]
        const isActive = active === kind
        return (
          <Button
            key={kind}
            type="button"
            variant={isActive ? 'default' : 'ghost'}
            size="sm"
            data-testid={`draw-tool-${kind}`}
            data-active={isActive ? 'true' : 'false'}
            aria-label={LABEL[kind]}
            title={LABEL[kind]}
            onClick={() => handle(kind)}
            className="h-7 w-7 p-0"
          >
            <Icon className="h-3 w-3" />
          </Button>
        )
      })}
    </div>
  )
}
