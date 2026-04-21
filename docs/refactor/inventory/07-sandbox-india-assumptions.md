# Inventory 07 — Sandbox/Analyzer India-specific assumptions

## Summary

Per ADR 0004, the analyzer stays India-limited. This inventory
documents the concrete Indian assumptions so they are visible — not
because they need to change, but because any future "universal
analyzer" project begins here.

Sandbox surface: `database/sandbox_db.py`, `services/sandbox_service.py`,
`sandbox/execution_engine.py`, `sandbox/order_manager.py`,
`sandbox/catch_up_processor.py`, `blueprints/sandbox.py`,
`blueprints/analyzer.py`, `upgrade/migrate_sandbox.py`.

## Raw citations

```
# Virtual capital in INR
database/sandbox_db.py:282
  "description": "Starting sandbox capital in INR (₹1 Crore) - Min: ₹1000"

# Auto square-off times — India-specific per exchange family
database/sandbox_db.py:305-322
  nse_bse_square_off_time   Square-off time for NSE/BSE MIS positions (IST)
  cds_bcd_square_off_time   Square-off time for CDS/BCD MIS positions (IST)
  mcx_square_off_time       Square-off time for MCX MIS positions (IST)
  ncdex_square_off_time     Square-off time for NCDEX MIS positions (IST)

# India-specific product types (MIS/CNC) in sandbox leverage config
database/sandbox_db.py:327,332,337
  "Leverage multiplier for equity MIS (NSE/BSE)"
  "Leverage multiplier for equity CNC (NSE/BSE)"
  "Leverage multiplier for all futures (NFO/BFO/CDS/BCD/MCX/NCDEX)"

# Migration seeds the same defaults
upgrade/migrate_sandbox.py:308-322
  ("reset_time", "00:00", "Time for automatic fund reset (IST)"),
  ("nse_bse_square_off_time", "15:15", ...),
  ("cds_bcd_square_off_time", "16:45", ...),
  ("mcx_square_off_time",     "23:30", ...),
  ("ncdex_square_off_time",   "17:00", ...),

# IST timezone usage throughout sandbox runtime
blueprints/analyzer.py:84,102              ist = pytz.timezone("Asia/Kolkata")
blueprints/sandbox.py:69,109,169,365,379,634   IST labels + reset timestamps
sandbox/execution_engine.py:228,325,335,352,397,638   datetime.now(pytz.timezone("Asia/Kolkata"))
sandbox/order_manager.py:122,126,169,572   "MIS orders cannot be placed after square-off time"
sandbox/catch_up_processor.py:21-58,153,224   IST = pytz.timezone("Asia/Kolkata"); daily PnL reset at 00:00 IST

# India-specific MIS enforcement
sandbox/order_manager.py:169
  "MIS orders cannot be placed after square-off time (...). Trading resumes at 09:00 AM IST."
```

## Blast radius

- **Phase 1b (plugin capabilities)** — `supports_analyzer: bool` is
  added, default `True` for `IN_stock` brokers, `False` for others.
- **Phase 7 (analyzer capability gating)** — backend short-circuits
  `/analyzer` routes with a capability-not-supported response when the
  active broker has `supports_analyzer=False`. Frontend hides the
  menu entry. **No changes to the India-specific analyzer logic.**
- Future "universal analyzer" work is **out of scope**. If a future
  ADR revisits it, this inventory is the entry point for scoping.

Invariant: the sandbox DB, margin engine, square-off scheduler stay
India-shaped. Capability gating hides them from non-Indian brokers.
