"""Phase 10 v4 (ADR 0023, ADR 0028) — Screener provider-pluggable scaffolding.

The Screener feature (webhook-driven screening signals → orders)
becomes provider-pluggable. The :class:`ScreenerProvider` contract
lives in :mod:`services.screeners.providers.base`. The dispatcher in
:mod:`services.screeners.dispatcher` resolves provider_code to a
registered provider; fail-closed when no provider is registered.

India provider: Chartink — preserves the existing webhook payload
parsing and India-shaped order mapping (NSE/BSE / MIS-CNC-NRML)
bit-identically.

Future US provider stub directory exists; v4 ships no US screener
implementation per the user clarification.
"""

from __future__ import annotations
