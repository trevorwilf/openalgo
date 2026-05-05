"""Alpaca legacy v1 data shim — ``BrokerData`` for intervals / quotes / history.

The legacy v1 services (``services.intervals_service``,
``services.quotes_service``, ``services.history_service``,
``services.depth_service``) dynamically import
``broker.<broker>.api.data`` and expect a ``BrokerData`` class with
specific attributes. This module is the Alpaca shim so those legacy
services don't 404 with "Broker-specific module not found" for any
operator running Alpaca.

Scope:

* ``timeframe_map`` — used by ``/api/v1/intervals``. Maps OpenAlgo
  interval strings (``1m`` / ``5m`` / ``15m`` / ``30m`` / ``1h`` /
  ``D``) onto Alpaca's native timeframes. Mirrors the
  ``_TIMEFRAME_MAP`` from ``broker.alpaca.api.bar_api`` so the two
  surfaces stay in sync.
* ``market_timings`` — US market session hours by exchange. Used
  internally by /history's date-range validator (and is informational
  for /intervals consumers).

Note: ``/api/v1/{quotes,depth,history}`` request schemas are locked
to Indian-market exchange enums (per ADR 0003 — frozen v1 contract).
A request with ``exchange=NASDAQ`` is rejected at the schema-validation
boundary, BEFORE this module is reached. Adding ``get_quotes`` /
``get_history`` methods here would not unlock those endpoints for
Alpaca via /api/v1; the operator would need the (sunsetting) /api/v1
schema relaxed first, or migrate to /api/v2/{quotes,bars} which
already work for Alpaca through the promoted-lane dispatcher.

This module's primary purpose is closing the ``/api/v1/intervals``
404 cleanly. The other legacy v1 data endpoints fall through to the
schema-validation 400 today and stay there until /api/v1 is sunset
or the schema is relaxed (an operator decision out of scope here).
"""

from __future__ import annotations

from typing import Any


class BrokerData:
    """Legacy v1 data handler for Alpaca.

    Constructed with ``auth_token`` (the OpenAlgo session token JSON
    blob from ``broker.alpaca.api.auth_api.authenticate_broker``).
    The token is held for use by future ``get_quotes`` /
    ``get_history`` methods if/when /api/v1 is widened.
    """

    def __init__(self, auth_token: str) -> None:
        self.auth_token = auth_token

        # OpenAlgo interval keys → Alpaca native timeframe strings.
        #
        # Built from ``broker.alpaca.api.bar_api._TIMEFRAME_MAP`` plus
        # the legacy single-letter aliases (``D`` / ``W`` / ``M``) the
        # /api/v1/intervals endpoint expects. The intervals service
        # categorizes by key suffix:
        #
        #   minutes ← endswith("m"); hours ← endswith("h");
        #   days/weeks/months ← exact ``D`` / ``W`` / ``M``
        #
        # Without the ``D`` alias, daily would be lost from
        # /api/v1/intervals output. Both keys map to the same native
        # ``"1Day"`` string so callers that pass either value work.
        from broker.alpaca.api.bar_api import _TIMEFRAME_MAP

        self.timeframe_map: dict[str, str] = dict(_TIMEFRAME_MAP)
        if "1d" in self.timeframe_map and "D" not in self.timeframe_map:
            self.timeframe_map["D"] = self.timeframe_map["1d"]

        # Approximate US equity market session windows by exchange.
        # The legacy v1 ``services.history_service`` consults this for
        # date-range validation; downstream consumers may inspect it
        # for display. Times are UTC-naive HH:MM strings matching the
        # legacy Indian-broker shape.
        #
        # NASDAQ / NYSE / ARCA / BATS all share the same regular
        # session (09:30–16:00 ET). The frozen v1 schema doesn't
        # expose extended-hours sessions; those live on the /api/v2
        # venues surface.
        self.market_timings: dict[str, dict[str, str]] = {
            "NASDAQ": {"start": "09:30:00", "end": "16:00:00"},
            "NYSE": {"start": "09:30:00", "end": "16:00:00"},
            "ARCA": {"start": "09:30:00", "end": "16:00:00"},
            "BATS": {"start": "09:30:00", "end": "16:00:00"},
        }
        self.default_market_timings: dict[str, str] = {
            "start": "09:30:00",
            "end": "16:00:00",
        }

    def get_market_timings(self, exchange: str) -> dict[str, str]:
        """Return the regular-session window for an exchange code."""
        return self.market_timings.get(
            (exchange or "").upper(), self.default_market_timings
        )


__all__ = ["BrokerData"]
