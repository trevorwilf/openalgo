// Phase 2 — Workspace Shell (display/execution skeleton trees)
//
// HANDOFF P-04: the display tree (read-only) and the execution tree
// (write-mediated) share NO mutable state. They communicate only via
// domain events and order ID.
//
// This module is the execution-tree root. It exports nothing in
// Phase 2; Phase 6 wires `<OrderEntryHUD>`, `<OrderModifyDrag>`,
// `<OrderCancel>`, and the pre-trade validation client here.
//
// The boundary exists from Phase 2 forward so Phase 6 can land its
// implementation in clean layers.

export {}
