// Phase 2 — Workspace Shell (display/execution skeleton trees)
//
// HANDOFF P-04: the display tree (read-only path — orders, positions,
// fills, strategy markers) and the execution tree (write-mediated
// path — order entry, modify, cancel) share NO mutable state. They
// communicate only via domain events and order ID.
//
// This module is the display-tree root. It exports nothing in
// Phase 2; Phase 6 wires `<OrderOverlayLayer>` and
// `<StrategySignalLayer>` here.
//
// The boundary exists from Phase 2 forward so Phase 6 can land its
// implementation in clean layers.

export {}
