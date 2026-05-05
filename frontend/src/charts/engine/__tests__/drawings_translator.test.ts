import { describe, expect, it } from 'vitest'
import {
  DRAWING_KINDS,
  type DrawingShape,
  fromKLineChartsOverlay,
  toKLineChartsOverlay,
} from '../drawings_translator'

describe('drawings translator', () => {
  it('lists 9 supported drawing kinds', () => {
    expect(DRAWING_KINDS.length).toBe(9)
    expect(new Set(DRAWING_KINDS)).toEqual(
      new Set([
        'trendline',
        'horizontal',
        'vertical',
        'ray',
        'rectangle',
        'ellipse',
        'fib_retracement',
        'fib_extension',
        'text',
      ])
    )
  })

  it('round-trips a trendline through klinecharts', () => {
    const shape: DrawingShape = {
      kind: 'trendline',
      points: [
        { t: 1700000000, price: 100 },
        { t: 1700001000, price: 110 },
      ],
    }
    const overlay = toKLineChartsOverlay(shape)
    expect(overlay).not.toBeNull()
    expect(overlay?.name).toBe('segment')
    expect(overlay?.points.length).toBe(2)
    const back = fromKLineChartsOverlay(overlay!)
    expect(back).toEqual(shape)
  })

  it('round-trips a rectangle', () => {
    const shape: DrawingShape = {
      kind: 'rectangle',
      a: { t: 1700000000, price: 100 },
      b: { t: 1700001000, price: 105 },
    }
    const overlay = toKLineChartsOverlay(shape)
    expect(overlay?.name).toBe('rectangle')
    const back = fromKLineChartsOverlay(overlay!)
    expect(back).toEqual(shape)
  })

  it('round-trips a fib retracement', () => {
    const shape: DrawingShape = {
      kind: 'fib_retracement',
      a: { t: 1700000000, price: 100 },
      b: { t: 1700001000, price: 90 },
    }
    const overlay = toKLineChartsOverlay(shape)
    expect(overlay?.name).toBe('fibonacciLine')
    const back = fromKLineChartsOverlay(overlay!)
    expect(back).toEqual(shape)
  })

  it('round-trips a text annotation', () => {
    const shape: DrawingShape = {
      kind: 'text',
      t: 1700000000,
      price: 100.5,
      text: 'breakout',
    }
    const overlay = toKLineChartsOverlay(shape)
    expect(overlay?.name).toBe('simpleAnnotation')
    expect(overlay?.text).toBe('breakout')
    const back = fromKLineChartsOverlay(overlay!)
    expect(back).toEqual(shape)
  })
})
