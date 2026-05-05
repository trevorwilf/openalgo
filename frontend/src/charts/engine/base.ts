// Phase 3 — engine adapter base utilities.
//
// Shared helpers used by every adapter. Pure logic, no engine module
// imports — keeps `lightweight-charts` / `klinecharts` / TradingView
// SDK references confined to their respective adapter modules per
// P-02.

import type { NormalizedBar } from '../types/bar'
import type { AdapterEvent } from './ChartEngineAdapter'

/** Decimal-string → number; null and non-numeric → NaN. */
export function dec(s: string | null | undefined): number {
  if (s == null) return Number.NaN
  const n = Number(s)
  return Number.isFinite(n) ? n : Number.NaN
}

export interface EventEmitter {
  emit(event: AdapterEvent): void
  subscribe(handler: (event: AdapterEvent) => void): () => void
}

/** Minimal pub-sub for adapter event streams. */
export function makeEventEmitter(): EventEmitter {
  const handlers = new Set<(event: AdapterEvent) => void>()
  return {
    emit(event) {
      for (const h of handlers) {
        try {
          h(event)
        } catch (err) {
          // Swallow handler errors so one bad subscriber can't poison
          // the emit. The adapter logs but does not surface to the host.
          // eslint-disable-next-line no-console
          console.error('[chart adapter] event handler threw', err)
        }
      }
    },
    subscribe(handler) {
      handlers.add(handler)
      return () => {
        handlers.delete(handler)
      }
    },
  }
}

/** Sort + dedupe bars by timestamp (latest write wins). */
export function normalizeBarSeries(bars: NormalizedBar[]): NormalizedBar[] {
  if (bars.length === 0) return []
  const byT = new Map<number, NormalizedBar>()
  for (const b of bars) byT.set(b.t, b)
  return [...byT.values()].sort((a, b) => a.t - b.t)
}

/** Group bars by `paneId` for adapters that mount each indicator/oscillator
 *  in its own pane. The first pane is conventionally the price pane. */
export function buildPaneIndex<T extends { paneId: string }>(items: T[]): Map<string, T[]> {
  const out = new Map<string, T[]>()
  for (const it of items) {
    const arr = out.get(it.paneId)
    if (arr) arr.push(it)
    else out.set(it.paneId, [it])
  }
  return out
}

/** Bridge values from `[{t, values: {key: number|null}}]` to the
 *  `[{time, value}]` shape lightweight-charts uses. Skips null values. */
export function toLineSeriesData(
  series: { t: number; values: Record<string, number | null> }[],
  key: string
): { time: number; value: number }[] {
  const out: { time: number; value: number }[] = []
  for (const row of series) {
    const v = row.values[key]
    if (v != null && Number.isFinite(v)) {
      out.push({ time: row.t, value: v })
    }
  }
  return out
}
