"""Phase 8 v4 (ADR 0023, ADR 0026) — Sandbox provider-pluggable scaffolding.

The Sandbox feature (paper trading / order simulation) is provider-
pluggable. The :class:`SandboxProvider` contract lives in
:mod:`services.sandbox.providers.base`. The dispatcher in
:mod:`services.sandbox.dispatcher` resolves the active broker's
region to a registered provider; fail-closed when no provider is
registered (HTTP 503 with code
``sandbox_provider_not_registered``).

India provider preserves all current Sandbox behavior bit-identically
(T+1 settlement, MIS / CNC / NRML, ₹10,00,000 initial funds, 15:15
IST square-off, no partial fills). US provider ships with mock data
(T+2 equity / T+1 option settlement, USD funds, partial fills,
XNYS 16:00 day-trade close).

Phase 8 of v4 ships the contract, the dispatcher, and minimal
India + US provider stubs. The full extraction of
``blueprints/sandbox.py`` and ``database/sandbox_db.py`` into the
provider pattern is a focused follow-up (Phase 8-bis).
"""

from __future__ import annotations
