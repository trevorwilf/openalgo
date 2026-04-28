"""Phase 3 v6 (ADR 0028 + EU region) — EU screener provider stub.

v6 ships NO EU screener implementation per the v6 prompt — real EU
screening would need an evaluated third-party service (Euronext-
specific webhook provider, future TradingView European screener,
etc.). This package exists so the dispatcher recognizes a future
EU provider without a structural change.

The contract is in :mod:`services.screeners.providers.base`. Adding
an EU screener is a single-file addition here:

    services/screeners/providers/eu/<provider_code>.py

with a class implementing :class:`ScreenerProvider`. Then register
it via ``services.screeners.dispatcher.register_screener_provider``.

Per ADR 0028 the screener dispatcher is keyed by provider_code (not
region); routing is per third-party service rather than per region.
"""

from __future__ import annotations
