import { describe, expect, it } from 'vitest'
import {
  cancelDrag,
  DEVIATION_THRESHOLD,
  endDrag,
  shouldCancelOnBoundary,
  startDrag,
  updateDrag,
} from '../OrderModifyDrag'

describe('OrderModifyDrag', () => {
  it('starts in the dragging state', () => {
    const s = startDrag('o1', 100)
    expect(s.dragging).toBe(true)
    expect(s.pendingConfirm).toBe(false)
    expect(s.proposed).toBeNull()
  })

  it('updateDrag tracks current price', () => {
    const s = updateDrag(startDrag('o1', 100), 102)
    expect(s.currentPrice).toBe(102)
  })

  it('endDrag flips deviationWarn=true when |Δ|/orig > 5%', () => {
    const s = endDrag(startDrag('o1', 100), 110)
    expect(s.dragging).toBe(false)
    expect(s.pendingConfirm).toBe(true)
    expect(s.proposed).toBe(110)
    expect(s.deviationWarn).toBe(true)
  })

  it('endDrag keeps deviationWarn=false when |Δ|/orig ≤ 5%', () => {
    const s = endDrag(startDrag('o1', 100), 104)
    expect(s.deviationWarn).toBe(false)
  })

  it('cancelDrag resets the state', () => {
    const a = endDrag(startDrag('o1', 100), 110)
    const b = cancelDrag(a)
    expect(b.dragging).toBe(false)
    expect(b.pendingConfirm).toBe(false)
    expect(b.proposed).toBeNull()
    expect(b.deviationWarn).toBe(false)
  })

  it('shouldCancelOnBoundary fires when drag exits chart bounds', () => {
    const s = startDrag('o1', 100)
    expect(shouldCancelOnBoundary(s, true)).toBe(false)
    expect(shouldCancelOnBoundary(s, false)).toBe(true)
  })

  it('threshold is 5%', () => {
    expect(DEVIATION_THRESHOLD).toBe(0.05)
  })
})
