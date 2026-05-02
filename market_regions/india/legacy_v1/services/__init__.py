"""Phase 9-bis-2 final-cleanup (T-35 push) — relocated India-only services.

These service modules implement India-shaped trading semantics
(NSE/NFO option chains, NSE market calendar, India options grammar,
IV / GEX / OI analytics tied to NIFTY / BANKNIFTY underlyings).
They were originally at ``services/<name>.py``; v9-bis-2 final
cleanup relocated them under this package as part of the T-35
LEGACY_INDIA bucket reduction. Shim modules at the original
``services.<name>`` path use ``sys.modules`` aliasing to keep
every existing importer working without per-callsite changes.
"""
from __future__ import annotations
