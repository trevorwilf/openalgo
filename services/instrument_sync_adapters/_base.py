"""T-26 (v7 Phase 7-bis) — region-neutral instrument sync base.

Extracted from ``zerodha_adapter.py`` so non-India broker
adapters (Alpaca / Schwab / Webull) read venue tz + base currency
from the active region plugin instead of redeclaring the
India-specific literals (``"Asia/Kolkata"`` / ``"INR"``).

Subclass contract:
* Set ``broker_code: str`` (class attribute).
* Set ``region_code: str`` (class attribute) — the broker's
  primary region. Default ``"india"`` for legacy India brokers
  that haven't been migrated.
* Override ``parse_rows()`` / ``fetch_csv()`` per the broker's
  raw format.

The base reads ``venue_timezone`` + ``currency`` from the region
plugin's metadata, with the historical India hard-coded values as
the fallback when the region plugin is unavailable (boot-time
contexts).
"""

from __future__ import annotations

from typing import Any


class BaseInstrumentSyncAdapter:
    """Region-neutral base for instrument-sync adapters."""

    broker_code: str = ""
    region_code: str = "india"  # legacy India default

    @property
    def venue_timezone(self) -> str:
        """Read tz from active region plugin's primary venue."""
        return self._region_attr(
            attr="timezone_name",
            india_fallback="Asia/Kolkata",
        )

    @property
    def currency(self) -> str:
        """Read base currency from active region plugin."""
        return self._region_attr(
            attr="default_currency",
            india_fallback="INR",
        )

    def _region_attr(self, *, attr: str, india_fallback: str) -> str:
        """Helper: read ``attr`` from the configured region plugin.

        Falls back to ``india_fallback`` when the region plugin is
        not loaded yet (test contexts, or boot-time before the
        plugin loader runs).
        """
        try:
            from utils.region_loader import get_market_region

            region = get_market_region(self.region_code)
            if region is None:
                from utils.region_loader import load_market_regions

                load_market_regions()
                region = get_market_region(self.region_code)
        except Exception:
            region = None

        if region is None:
            return india_fallback

        value = getattr(region, attr, None)
        if value:
            return str(value)
        return india_fallback


class USBrokerSyncAdapterBase(BaseInstrumentSyncAdapter):
    """T-26 — shared base for Alpaca / Schwab / Webull.

    Sets ``region_code = "us"`` so subclasses don't repeat it.
    Adapters override ``broker_code`` and the parse/fetch methods.
    """

    region_code: str = "us"


__all__ = ["BaseInstrumentSyncAdapter", "USBrokerSyncAdapterBase"]
