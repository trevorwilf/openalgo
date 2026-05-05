// Phase 6 — drag-to-modify state machine + 5% deviation guard.
//
// HANDOFF P-10: drag-to-modify confirmation is OPT-IN, default OFF.
// When the user drags an order line and releases:
//   * if `|new_price - current_price| / current_price > 5%`, surface
//     a banner-warn before allowing confirm.
//   * the modify-confirm modal is identical to the place-confirm modal
//     in OrderEntryHUD (two-step, ESC cancels, Enter never confirms).
//
// This module is a pure state machine — it has no React deps so the
// engine adapter can drive it from pixel events. The host wires the
// emitted state transitions into a confirmation UI.

export interface ModifyDragState {
  orderId: string
  originalPrice: number
  currentPrice: number
  /** Drag started (mousedown on order line). */
  dragging: boolean
  /** Drag ended (mouseup); awaiting user confirmation. */
  pendingConfirm: boolean
  /** When pendingConfirm = true, this is the proposed new price. */
  proposed: number | null
  /** True when |proposed - originalPrice| / originalPrice > 5%. */
  deviationWarn: boolean
}

export const DEVIATION_THRESHOLD = 0.05

export function startDrag(orderId: string, originalPrice: number): ModifyDragState {
  return {
    orderId,
    originalPrice,
    currentPrice: originalPrice,
    dragging: true,
    pendingConfirm: false,
    proposed: null,
    deviationWarn: false,
  }
}

export function updateDrag(state: ModifyDragState, currentPrice: number): ModifyDragState {
  if (!state.dragging) return state
  return { ...state, currentPrice }
}

export function endDrag(state: ModifyDragState, proposed: number): ModifyDragState {
  if (!state.dragging) return state
  const dev =
    state.originalPrice > 0 ? Math.abs(proposed - state.originalPrice) / state.originalPrice : 0
  return {
    ...state,
    dragging: false,
    pendingConfirm: true,
    proposed,
    deviationWarn: dev > DEVIATION_THRESHOLD,
  }
}

export function cancelDrag(state: ModifyDragState): ModifyDragState {
  return {
    ...state,
    dragging: false,
    pendingConfirm: false,
    proposed: null,
    deviationWarn: false,
  }
}

/** True when the user-issued drag is at the boundary of the chart and
 *  must be cancelled. The host computes this against the chart's
 *  bounding box per Phase 6 acceptance scenario 5. */
export function shouldCancelOnBoundary(state: ModifyDragState, withinBounds: boolean): boolean {
  return state.dragging && !withinBounds
}
