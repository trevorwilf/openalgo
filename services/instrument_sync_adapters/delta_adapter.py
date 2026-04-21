"""Delta Exchange instrument-sync adapter.

Reads the Delta Exchange `/v2/products` endpoint that
`broker/deltaexchange/database/master_contract_db.py` also reads. Same
pattern as the Zerodha adapter: the source is injectable so tests can
feed a local JSON fixture.

Delta product_type values encountered:
    spot               → AssetClass.SPOT,       InstrumentKind.CASH
    perpetual_futures  → AssetClass.PERPETUAL,  InstrumentKind.DERIVATIVE
    futures            → AssetClass.FUTURE,     InstrumentKind.DERIVATIVE
    call_options       → AssetClass.OPTION,     option_right=CALL
    put_options        → AssetClass.OPTION,     option_right=PUT

For options we populate expiration_at, strike, option_right. For
perpetuals the underlying is recorded via the `underlying_canonical_symbol`
hint; Phase 3+ resolver wires the FK when the spot row exists.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any, Iterable, Optional

from services.instrument_sync_service import (
    IdentifierRecord,
    NormalizedInstrumentRow,
    RawInstrumentRow,
)
from utils.logging import get_logger

logger = get_logger(__name__)


DEFAULT_DELTA_URL = "https://api.india.delta.exchange/v2/products"


_PRODUCT_TYPE_TO_ASSET_CLASS: dict[str, tuple[str, str, Optional[str]]] = {
    "spot": ("SPOT", "CASH", None),
    "perpetual_futures": ("PERPETUAL", "DERIVATIVE", None),
    "futures": ("FUTURE", "DERIVATIVE", None),
    "call_options": ("OPTION", "DERIVATIVE", "CALL"),
    "put_options": ("OPTION", "DERIVATIVE", "PUT"),
}


class DeltaAdapter:
    """Delta Exchange instrument sync adapter.

    Construct with either `json_path` (tests) or `products_url` +
    optional `http_client` (production).
    """

    broker_code = "deltaexchange"
    venue_code = "DELTA_EXCHANGE"
    venue_timezone = "UTC"

    def __init__(
        self,
        *,
        json_path: Optional[str | Path] = None,
        products_url: str = DEFAULT_DELTA_URL,
        http_client: Optional[Any] = None,
    ) -> None:
        self._json_path = Path(json_path) if json_path is not None else None
        self._products_url = products_url
        self._http_client = http_client

    # ------------------------------------------------------------------
    # Protocol: fetch_raw

    def fetch_raw(self) -> Iterable[RawInstrumentRow]:
        if self._json_path is not None:
            payload = json.loads(self._json_path.read_text(encoding="utf-8"))
        else:
            payload = self._download_products()
        for product in payload.get("result", []):
            yield product

    def _download_products(self) -> dict[str, Any]:
        if self._http_client is not None:
            resp = self._http_client.get(self._products_url)
            resp.raise_for_status()
            return resp.json()
        import httpx

        with httpx.Client(timeout=60.0) as client:
            resp = client.get(self._products_url)
            resp.raise_for_status()
            return resp.json()

    # ------------------------------------------------------------------
    # Protocol: normalize

    def normalize(self, raw: RawInstrumentRow) -> Optional[NormalizedInstrumentRow]:
        product_type = str(raw.get("product_type", "")).strip().lower()
        classification = _PRODUCT_TYPE_TO_ASSET_CLASS.get(product_type)
        if classification is None:
            logger.debug(
                "delta: skipping product with unknown product_type=%r id=%s",
                product_type, raw.get("id"),
            )
            return None
        asset_class, instrument_kind, option_right = classification

        symbol = str(raw.get("symbol", "")).strip()
        if not symbol:
            return None

        product_id = raw.get("id")
        external_token = str(product_id) if product_id is not None else None

        expiration = _parse_delta_expiry(raw.get("settlement_time"))
        strike = _parse_decimal(raw.get("strike_price"))
        tick_size = _parse_decimal(raw.get("tick_size"))
        lot_size = _parse_int(raw.get("contract_unit_currency_scale"))  # best-effort

        underlying = str(raw.get("underlying_asset_symbol", "")).strip() or None
        quoting = str(raw.get("quoting_asset_symbol", "")).strip() or None

        display_name = (raw.get("description") or symbol).strip() or None

        identifiers: list[IdentifierRecord] = [
            IdentifierRecord(
                identifier_type="VENUE_SYMBOL",
                identifier_value=symbol,
                venue_code=self.venue_code,
            ),
            IdentifierRecord(
                identifier_type="BROKER_SYMBOL",
                identifier_value=symbol,
                broker_code=self.broker_code,
                venue_code=self.venue_code,
            ),
        ]
        if external_token is not None:
            identifiers.append(
                IdentifierRecord(
                    identifier_type="BROKER_TOKEN",
                    identifier_value=external_token,
                    broker_code=self.broker_code,
                    venue_code=self.venue_code,
                )
            )

        return NormalizedInstrumentRow(
            venue_code=self.venue_code,
            market_family="CRYPTO",
            venue_timezone=self.venue_timezone,
            canonical_symbol=symbol,
            asset_class=asset_class,
            instrument_kind=instrument_kind,
            external_symbol=symbol,
            external_token=external_token,
            tick_size=tick_size,
            lot_size=lot_size,
            expiration_at=expiration,
            option_right=option_right,
            strike=strike,
            currency=quoting,
            display_name=display_name,
            underlying_canonical_symbol=underlying,
            identifiers=identifiers,
            metadata={"product_type": product_type} if product_type else None,
        )

    # ------------------------------------------------------------------
    # Protocol: resolve_venue / resolve_identifiers

    def resolve_venue(self, normalized: NormalizedInstrumentRow) -> str:
        return normalized.venue_code

    def resolve_identifiers(
        self, normalized: NormalizedInstrumentRow
    ) -> list[IdentifierRecord]:
        return list(normalized.identifiers)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _parse_delta_expiry(value: Any) -> Optional[datetime]:
    """Delta's `settlement_time` is an ISO-8601 string (UTC). Accept
    both `...Z` and `...+00:00` forms."""
    if value is None:
        return None
    raw = str(value).strip()
    if not raw:
        return None
    # Normalize trailing Z to +00:00 for fromisoformat
    normalized = raw.replace("Z", "+00:00")
    try:
        dt = datetime.fromisoformat(normalized)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


def _parse_decimal(value: Any) -> Optional[Decimal]:
    if value is None:
        return None
    raw = str(value).strip()
    if not raw:
        return None
    try:
        return Decimal(raw)
    except (InvalidOperation, ValueError):
        return None


def _parse_int(value: Any) -> Optional[int]:
    if value is None:
        return None
    raw = str(value).strip()
    if not raw:
        return None
    try:
        return int(Decimal(raw))
    except (InvalidOperation, ValueError):
        return None


__all__ = ["DeltaAdapter"]
