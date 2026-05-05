// Phase 5 — IndicatorManager modal.
//
// Add/remove/configure indicators per cell. Catalog comes from
// frontend/src/charts/types/indicators.ts (mirrors Python).
// Persistence wires through /api/v2/chart/indicators (Phase 1
// skeleton + Phase 5 full CRUD).

import { Plus, Trash2, X } from 'lucide-react'
import { type FormEvent, useCallback, useEffect, useState } from 'react'
import { Button } from '@/components/ui/button'
import { cn } from '@/lib/utils'
import { getIndicator, INDICATOR_CATALOG, type IndicatorDef } from '../types/indicators'

export interface IndicatorRow {
  id: number
  layout_id: number
  cell_id: string
  indicator_key: string
  params_json: Record<string, number | string | boolean>
}

export interface IndicatorManagerProps {
  cellId: string
  layoutId: number
  apikey: string | null
  open: boolean
  onClose(): void
  fetchImpl?: typeof fetch
}

export function IndicatorManager({
  cellId,
  layoutId,
  apikey,
  open,
  onClose,
  fetchImpl,
}: IndicatorManagerProps) {
  const fetchFn = fetchImpl ?? fetch
  const [rows, setRows] = useState<IndicatorRow[]>([])
  const [error, setError] = useState<string | null>(null)
  const [pickKey, setPickKey] = useState<string>('SMA')

  const reload = useCallback(async () => {
    if (!apikey) return
    setError(null)
    try {
      const res = await fetchFn(
        `/api/v2/chart/indicators?apikey=${encodeURIComponent(apikey)}&layout_id=${layoutId}&cell_id=${encodeURIComponent(cellId)}`,
        { credentials: 'same-origin' }
      )
      if (!res.ok) {
        setError(`HTTP ${res.status}`)
        return
      }
      const json = (await res.json()) as { data?: IndicatorRow[] }
      setRows(json.data ?? [])
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err))
    }
  }, [apikey, layoutId, cellId, fetchFn])

  useEffect(() => {
    if (open) void reload()
  }, [open, reload])

  const handleAdd = useCallback(
    async (e: FormEvent) => {
      e.preventDefault()
      if (!apikey) return
      const def = getIndicator(pickKey)
      if (!def) return
      const params: Record<string, number | string | boolean> = {}
      for (const p of def.params) params[p.name] = p.default
      try {
        const res = await fetchFn('/api/v2/chart/indicators', {
          method: 'POST',
          credentials: 'same-origin',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            apikey,
            layout_id: layoutId,
            cell_id: cellId,
            indicator_key: def.key,
            params_json: params,
          }),
        })
        if (!res.ok) {
          setError(`HTTP ${res.status}`)
          return
        }
        await reload()
      } catch (err) {
        setError(err instanceof Error ? err.message : String(err))
      }
    },
    [apikey, layoutId, cellId, pickKey, fetchFn, reload]
  )

  const handleRemove = useCallback(
    async (id: number) => {
      if (!apikey) return
      try {
        await fetchFn(`/api/v2/chart/indicators/${id}?apikey=${encodeURIComponent(apikey)}`, {
          method: 'DELETE',
          credentials: 'same-origin',
        })
        await reload()
      } catch (err) {
        setError(err instanceof Error ? err.message : String(err))
      }
    },
    [apikey, fetchFn, reload]
  )

  if (!open) return null

  return (
    <div
      data-testid="indicator-manager"
      className={cn(
        'fixed inset-0 z-50 flex items-center justify-center bg-black/40',
        'pointer-events-auto'
      )}
      onClick={onClose}
      onKeyDown={(e) => {
        if (e.key === 'Escape') onClose()
      }}
      role="dialog"
      aria-modal="true"
    >
      <div
        className="w-full max-w-md rounded-md border bg-background p-4 shadow-lg"
        onClick={(e) => e.stopPropagation()}
        onKeyDown={(e) => e.stopPropagation()}
        role="document"
      >
        <header className="mb-2 flex items-center justify-between">
          <h2 className="text-base font-medium">Indicators</h2>
          <button type="button" aria-label="Close" onClick={onClose}>
            <X className="h-4 w-4" />
          </button>
        </header>
        {error && (
          <p data-testid="indicator-manager-error" className="mb-2 text-xs text-destructive">
            {error}
          </p>
        )}
        <ul className="mb-3 max-h-72 space-y-1 overflow-y-auto" data-testid="indicator-list">
          {rows.length === 0 && (
            <li className="rounded-sm border border-dashed p-2 text-xs text-muted-foreground">
              No indicators on this cell yet.
            </li>
          )}
          {rows.map((r) => (
            <li
              key={r.id}
              data-testid={`indicator-row-${r.id}`}
              className="flex items-center justify-between rounded-sm border bg-card px-2 py-1 text-xs"
            >
              <span>
                <span className="font-medium">{r.indicator_key}</span>
                {Object.keys(r.params_json || {}).length > 0 && (
                  <span className="ml-2 text-muted-foreground">
                    {Object.entries(r.params_json)
                      .map(([k, v]) => `${k}=${v}`)
                      .join(', ')}
                  </span>
                )}
              </span>
              <button
                type="button"
                onClick={() => handleRemove(r.id)}
                aria-label="Remove"
                className="text-muted-foreground hover:text-destructive"
                data-testid={`indicator-remove-${r.id}`}
              >
                <Trash2 className="h-3 w-3" />
              </button>
            </li>
          ))}
        </ul>
        <form onSubmit={handleAdd} className="flex items-center gap-2">
          <select
            data-testid="indicator-picker"
            value={pickKey}
            onChange={(e) => setPickKey(e.target.value)}
            className="flex-1 rounded-sm border bg-background px-2 py-1 text-xs"
            aria-label="Pick indicator"
          >
            {INDICATOR_CATALOG.map((d: IndicatorDef) => (
              <option key={d.key} value={d.key}>
                {d.label} ({d.key})
              </option>
            ))}
          </select>
          <Button type="submit" size="sm" data-testid="indicator-add">
            <Plus className="mr-1 h-3 w-3" />
            Add
          </Button>
        </form>
      </div>
    </div>
  )
}
