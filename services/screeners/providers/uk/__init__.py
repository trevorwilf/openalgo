"""Phase 3 v6 (ADR 0028 + UK region) — UK screener provider stub.

v6 ships NO UK screener implementation per the v6 prompt. Mirror of
the EU stub.

Real UK screening would need an evaluated third-party service (LSE-
specific webhook provider, future TradingView UK screener, etc.).
This package exists so the dispatcher recognizes a future UK
provider without a structural change.
"""

from __future__ import annotations
