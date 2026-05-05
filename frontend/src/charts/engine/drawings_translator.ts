// Phase 5 — engine-agnostic drawing schema translator.
//
// OpenAlgo-native drawing shape (the wire shape persisted in
// `chart_drawings.params_json`):
//
//   { kind: 'trendline', points: [{ t, price }, { t, price }] }
//   { kind: 'horizontal', price }
//   { kind: 'vertical', t }
//   { kind: 'ray', anchor: { t, price }, slope }
//   { kind: 'rectangle', a: { t, price }, b: { t, price } }
//   { kind: 'ellipse', center: { t, price }, rx, ry }
//   { kind: 'fib_retracement', a: { t, price }, b: { t, price }, levels }
//   { kind: 'fib_extension', a: { t, price }, b: { t, price }, c: ..., levels }
//   { kind: 'text', t, price, text }
//
// Each engine adapter translates this shape to/from its native
// drawing API. KLineChart Pro uses a richer overlay model with
// `name` + `points`; Lightweight uses Series Primitives. The
// translator below maps just the OpenAlgo shape — engine-side
// custom-primitives are wired in the adapter modules.

export type DrawingPoint = { t: number; price: number }

export type DrawingShape =
  | { kind: 'trendline'; points: [DrawingPoint, DrawingPoint] }
  | { kind: 'horizontal'; price: number }
  | { kind: 'vertical'; t: number }
  | { kind: 'ray'; anchor: DrawingPoint; slope: number }
  | { kind: 'rectangle'; a: DrawingPoint; b: DrawingPoint }
  | { kind: 'ellipse'; center: DrawingPoint; rx: number; ry: number }
  | { kind: 'fib_retracement'; a: DrawingPoint; b: DrawingPoint; levels?: number[] }
  | { kind: 'fib_extension'; a: DrawingPoint; b: DrawingPoint; c: DrawingPoint; levels?: number[] }
  | { kind: 'text'; t: number; price: number; text: string }

export const DRAWING_KINDS: ReadonlyArray<DrawingShape['kind']> = [
  'trendline',
  'horizontal',
  'vertical',
  'ray',
  'rectangle',
  'ellipse',
  'fib_retracement',
  'fib_extension',
  'text',
] as const

/** Convert a klinecharts overlay payload into the OpenAlgo shape.
 *  The expected `overlay` shape carries `name` + `points: [{timestamp, value}]`. */
export function fromKLineChartsOverlay(overlay: {
  name: string
  points: Array<{ timestamp: number; value: number }>
  text?: string
}): DrawingShape | null {
  const pts = overlay.points.map((p) => ({ t: Math.floor(p.timestamp / 1000), price: p.value }))
  const name = overlay.name
  if (name === 'segment' && pts.length === 2) {
    return { kind: 'trendline', points: [pts[0], pts[1]] }
  }
  if (name === 'horizontalRayLine' && pts.length === 1) {
    return { kind: 'horizontal', price: pts[0].price }
  }
  if (name === 'verticalRayLine' && pts.length === 1) {
    return { kind: 'vertical', t: pts[0].t }
  }
  if (name === 'rectangle' && pts.length === 2) {
    return { kind: 'rectangle', a: pts[0], b: pts[1] }
  }
  if (name === 'circle' && pts.length === 2) {
    const cx = (pts[0].t + pts[1].t) / 2
    const cy = (pts[0].price + pts[1].price) / 2
    const rx = Math.abs(pts[1].t - pts[0].t) / 2
    const ry = Math.abs(pts[1].price - pts[0].price) / 2
    return { kind: 'ellipse', center: { t: cx, price: cy }, rx, ry }
  }
  if (name === 'fibonacciLine' && pts.length === 2) {
    return { kind: 'fib_retracement', a: pts[0], b: pts[1] }
  }
  if (name === 'simpleAnnotation' && pts.length === 1 && overlay.text) {
    return { kind: 'text', t: pts[0].t, price: pts[0].price, text: overlay.text }
  }
  return null
}

/** Convert an OpenAlgo drawing shape to the klinecharts overlay payload. */
export function toKLineChartsOverlay(shape: DrawingShape): {
  name: string
  points: Array<{ timestamp: number; value: number }>
  text?: string
} | null {
  switch (shape.kind) {
    case 'trendline':
      return {
        name: 'segment',
        points: shape.points.map((p) => ({ timestamp: p.t * 1000, value: p.price })),
      }
    case 'horizontal':
      return { name: 'horizontalRayLine', points: [{ timestamp: 0, value: shape.price }] }
    case 'vertical':
      return { name: 'verticalRayLine', points: [{ timestamp: shape.t * 1000, value: 0 }] }
    case 'rectangle':
      return {
        name: 'rectangle',
        points: [
          { timestamp: shape.a.t * 1000, value: shape.a.price },
          { timestamp: shape.b.t * 1000, value: shape.b.price },
        ],
      }
    case 'ellipse':
      return {
        name: 'circle',
        points: [
          { timestamp: (shape.center.t - shape.rx) * 1000, value: shape.center.price - shape.ry },
          { timestamp: (shape.center.t + shape.rx) * 1000, value: shape.center.price + shape.ry },
        ],
      }
    case 'fib_retracement':
      return {
        name: 'fibonacciLine',
        points: [
          { timestamp: shape.a.t * 1000, value: shape.a.price },
          { timestamp: shape.b.t * 1000, value: shape.b.price },
        ],
      }
    case 'text':
      return {
        name: 'simpleAnnotation',
        points: [{ timestamp: shape.t * 1000, value: shape.price }],
        text: shape.text,
      }
    default:
      return null
  }
}

/** Stable round-trip: shape → engine-A → openalgo-shape → engine-B
 *  → engine-A → openalgo-shape must be idempotent for every kind that
 *  engine A and B both support. The drawing toolbar test in
 *  __tests__/drawings_translator.test.ts asserts this for every
 *  supported shape. */
