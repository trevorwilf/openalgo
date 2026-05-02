"""Phase 9-bis-2 final-cleanup — relocated India-only utility modules.

India-shaped helpers (MPP slab math tied to NSE/NFO market price
protection rules, Indian symbol parsing helpers, etc.). Shim
modules at the original ``utils.<name>`` path use ``sys.modules``
aliasing to keep every existing importer working without
per-callsite changes.
"""
from __future__ import annotations
