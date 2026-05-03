"""Alpaca instrument-sync adapter.

Bridges Alpaca's ``GET /v2/assets`` JSON feed into the framework's
:class:`~services.instrument_sync_service.InstrumentSyncRunner`. The
runner shares the canonical ``database.instruments_repo`` write path
that ``broker/alpaca/sync/instrument_sync.py`` uses today; this
adapter is the framework integration so the scheduler picks
Alpaca up alongside zerodha + deltaexchange.

Source: Alpaca's REST endpoint ``GET /v2/assets?status=active``.
Returns one JSON object per tradable asset:

    {
      "id": "...",
      "class": "us_equity",
      "exchange": "NASDAQ" | "NYSE" | "ARCA" | "BATS" | "AMEX" | "OTC",
      "symbol": "AAPL",
      "name": "Apple Inc.",
      "status": "active" | "inactive",
      "tradable": true,
      "shortable": true,
      "fractionable": true,
      "easy_to_borrow": true,
      ...
    }

Venue mapping mirrors ``broker/alpaca/sync/instrument_sync._normalize_venue``
so both code paths agree on the canonical OpenAlgo venue codes.
"""

from __future__ import annotations

import json
from collections.abc import Iterable
from decimal import Decimal
from pathlib import Path
from typing import Any, Optional

from services.instrument_sync_service import (
    IdentifierRecord,
    NormalizedInstrumentRow,
    RawInstrumentRow,
)
from utils.logging import get_logger

logger = get_logger(__name__)


# Branch N — single source of truth for the Alpaca exchange ↔ venue
# mapping lives in ``broker.alpaca.mapping.transform_data``. This
# adapter imports the canonical table rather than maintaining a
# parallel inline copy.
from broker.alpaca.mapping.transform_data import (
    ALPACA_EXCHANGE_TO_VENUE as _EXCHANGE_TO_VENUE,
)


class AlpacaAdapter:
    """Alpaca instrument sync adapter.

    Construct with a local ``json_path`` (tests / fixture-driven runs)
    or with an HTTP client (production: pulls live ``/v2/assets``).
    Exactly one of the two should be set; if both are unset a runtime
    fetch via the operator's broker-resolved ``AlpacaAuth`` is used.
    """

    broker_code = "alpaca"
    venue_timezone = "America/New_York"
    market_family = "US_STOCK"

    def __init__(
        self,
        *,
        json_path: Optional[str | Path] = None,
        http_client: Optional[Any] = None,
        auth: Optional[Any] = None,
    ) -> None:
        self._json_path = Path(json_path) if json_path is not None else None
        self._http_client = http_client
        self._auth = auth

    # ------------------------------------------------------------------
    # Protocol: fetch_raw

    def fetch_raw(self) -> Iterable[RawInstrumentRow]:
        """Yield one dict per Alpaca asset row.

        Local-file source is preferred when set (tests). Production
        fetches via the injected http_client or, if absent, calls
        ``broker.alpaca.sync.instrument_sync.fetch_assets`` which
        uses the standard Alpaca auth flow.
        """
        if self._json_path is not None:
            with self._json_path.open("r", encoding="utf-8") as f:
                rows = json.load(f)
            yield from rows
            return

        # Defer the import so test paths that only hit fixtures don't
        # drag in httpx + the auth machinery.
        from broker.alpaca.sync.instrument_sync import fetch_assets

        rows = fetch_assets(auth=self._auth, client=self._http_client)
        yield from rows

    # ------------------------------------------------------------------
    # Protocol: normalize

    def normalize(self, raw: RawInstrumentRow) -> Optional[NormalizedInstrumentRow]:
        symbol = (raw.get("symbol") or "").strip()
        if not symbol:
            return None

        exchange_str = (raw.get("exchange") or "").strip().upper()
        venue = _EXCHANGE_TO_VENUE.get(exchange_str)
        if venue is None:
            logger.debug(
                "alpaca: skipping row — unmapped exchange=%r symbol=%r",
                exchange_str,
                symbol,
            )
            return None

        # Alpaca's tradable=False rows are still surfaced in /v2/assets
        # (status=active just means the listing is recognized). Keep
        # them — downstream order-routing checks tradable separately.
        asset_class_raw = (raw.get("class") or "").strip().lower()
        if asset_class_raw in ("us_equity", ""):
            asset_class = "EQUITY"
            instrument_kind = "CASH"
        elif asset_class_raw == "crypto":
            asset_class = "SPOT"
            instrument_kind = "CASH"
        else:
            logger.debug(
                "alpaca: skipping row — unsupported asset_class=%r symbol=%r",
                asset_class_raw,
                symbol,
            )
            return None

        # Alpaca tick size is fixed at 0.01 for sub-$1 / above-$1 stocks
        # in the canonical filing; intraday some symbols quote sub-cent
        # but those are pricing-side concerns. The instrument record
        # carries the canonical 0.01 minimum.
        tick_size = Decimal("0.01")
        # Fractionable instruments support 9-decimal precision; whole-
        # share-only instruments use 0.
        quantity_precision = 9 if raw.get("fractionable") else 0

        external_token = str(raw.get("id") or "").strip() or None

        identifiers: list[IdentifierRecord] = []
        if external_token:
            identifiers.append(
                IdentifierRecord(
                    identifier_type="BROKER_TOKEN",
                    identifier_value=external_token,
                    broker_code=self.broker_code,
                    venue_code=venue,
                )
            )

        metadata = {
            "alpaca_id": raw.get("id"),
            "alpaca_class": raw.get("class"),
            "alpaca_exchange": raw.get("exchange"),
            "tradable": raw.get("tradable"),
            "shortable": raw.get("shortable"),
            "easy_to_borrow": raw.get("easy_to_borrow"),
            "fractionable": raw.get("fractionable"),
            "maintenance_margin_requirement": raw.get(
                "maintenance_margin_requirement"
            ),
            "marginable": raw.get("marginable"),
            "status": raw.get("status"),
        }
        # Drop None values from metadata so the JSON column stays compact.
        metadata = {k: v for k, v in metadata.items() if v is not None}

        return NormalizedInstrumentRow(
            venue_code=venue,
            market_family=self.market_family,
            venue_timezone=self.venue_timezone,
            canonical_symbol=symbol,
            asset_class=asset_class,
            instrument_kind=instrument_kind,
            external_symbol=symbol,
            external_token=external_token,
            tick_size=tick_size,
            quantity_precision=quantity_precision,
            currency="USD",
            display_name=(raw.get("name") or "").strip() or None,
            metadata=metadata,
            identifiers=identifiers,
        )


__all__ = ["AlpacaAdapter"]
