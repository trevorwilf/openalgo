"""Phase 10 v4 (ADR 0028) — US screener provider stub.

v4 ships NO US screener implementation per the user clarification —
real Schwab/Webull screening would need an evaluated third-party
service (TradingView screener webhook, future Alpaca screener, etc.).
This package exists so the dispatcher can recognize a future US
provider without a structural change.

The contract is in :mod:`services.screeners.providers.base`. Adding
a US screener is a single-file addition here:

    services/screeners/providers/us/<provider_code>.py

with a class implementing :class:`ScreenerProvider`. Then register
it via ``services.screeners.dispatcher.register_screener_provider``.

Phase 10 of v4 ships the framework; the US provider implementation
itself is out of v4 scope.
"""

from __future__ import annotations
