"""Zerodha instrument-sync adapter.

Reads the same CSV that `broker/zerodha/database/master_contract_db.py`
reads (Kite instruments dump — the canonical source for Indian symbols
via this broker). This adapter does **not** import or invoke the legacy
sync module; it reads from an injectable path/URL and normalizes each
CSV row into a `NormalizedInstrumentRow`.

Kite CSV columns (reference):

    instrument_token, exchange_token, tradingsymbol, name, last_price,
    expiry, strike, tick_size, lot_size, instrument_type, segment,
    exchange

Venue mapping:
    NSE / BSE / NFO / BFO / MCX / CDS + NSE_INDEX (segment=="NSE/INDICES")
    + BSE_INDEX (segment=="BSE/INDICES").

Asset-class mapping:
    EQ   → EQUITY
    FUT  → FUTURE
    CE   → OPTION (option_right=CALL)
    PE   → OPTION (option_right=PUT)
    INDEX segments → INDEX (underlyings like NIFTY, BANKNIFTY)
"""

from __future__ import annotations

import csv
import io
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


DEFAULT_KITE_URL = "https://api.kite.trade/instruments"


# Kite segment strings → OpenAlgo venue_code.
_SEGMENT_TO_VENUE: dict[str, str] = {
    "NSE": "NSE",
    "BSE": "BSE",
    "NFO-OPT": "NFO",
    "NFO-FUT": "NFO",
    "BFO-OPT": "BFO",
    "BFO-FUT": "BFO",
    "MCX-OPT": "MCX",
    "MCX-FUT": "MCX",
    "CDS-OPT": "CDS",
    "CDS-FUT": "CDS",
    "BCD-OPT": "BCD",
    "BCD-FUT": "BCD",
    "NSE/INDICES": "NSE_INDEX",
    "BSE/INDICES": "BSE_INDEX",
}


class ZerodhaAdapter:
    """Zerodha instrument sync adapter.

    Construct with either a local `csv_path` (tests) or a `csv_url`
    (production). Exactly one must be set.
    """

    broker_code = "zerodha"
    venue_timezone = "Asia/Kolkata"

    def __init__(
        self,
        *,
        csv_path: Optional[str | Path] = None,
        csv_url: str = DEFAULT_KITE_URL,
        http_client: Optional[Any] = None,
    ) -> None:
        self._csv_path = Path(csv_path) if csv_path is not None else None
        self._csv_url = csv_url
        self._http_client = http_client

    # ------------------------------------------------------------------
    # Protocol: fetch_raw

    def fetch_raw(self) -> Iterable[RawInstrumentRow]:
        """Yield one dict per CSV row.

        Local-file source is preferred when set (tests). Production uses
        the injected HTTP client (so callers can share the project's
        pooled `httpx` instance) or lazily downloads otherwise.
        """
        if self._csv_path is not None:
            with self._csv_path.open("r", encoding="utf-8", newline="") as f:
                yield from csv.DictReader(f)
            return

        text = self._download_csv()
        yield from csv.DictReader(io.StringIO(text))

    def _download_csv(self) -> str:
        if self._http_client is not None:
            resp = self._http_client.get(self._csv_url)
            resp.raise_for_status()
            return resp.text
        # Late import so tests that only hit fixtures don't drag httpx in.
        import httpx

        with httpx.Client(timeout=60.0) as client:
            resp = client.get(self._csv_url)
            resp.raise_for_status()
            return resp.text

    # ------------------------------------------------------------------
    # Protocol: normalize

    def normalize(self, raw: RawInstrumentRow) -> Optional[NormalizedInstrumentRow]:
        segment = str(raw.get("segment", "")).strip()
        venue = _SEGMENT_TO_VENUE.get(segment)
        if venue is None:
            # Unknown segment — log and skip rather than crashing the whole sync.
            logger.debug("zerodha: skipping row with unknown segment %r", segment)
            return None

        inst_type = str(raw.get("instrument_type", "")).strip().upper()
        asset_class, instrument_kind, option_right = _classify(inst_type, venue)
        if asset_class is None:
            logger.debug(
                "zerodha: skipping row — unclassified instrument_type=%r venue=%s",
                inst_type, venue,
            )
            return None

        canonical_symbol = str(raw.get("tradingsymbol", "")).strip()
        if not canonical_symbol:
            return None

        external_symbol = canonical_symbol  # Kite tradingsymbol is broker-facing
        # Kite composes its token as instrument_token::::exchange_token in
        # the legacy pipeline; we keep just the instrument_token as the
        # external_token here since Phase 2a's broker_instrument_map treats
        # token as opaque.
        external_token = str(raw.get("instrument_token", "")).strip() or None

        expiry = _parse_kite_expiry(raw.get("expiry"))
        strike = _parse_decimal(raw.get("strike"))
        if strike is not None and strike == Decimal("0"):
            strike = None  # Kite sometimes writes 0 for non-option rows

        tick_size = _parse_decimal(raw.get("tick_size"))
        lot_size = _parse_int(raw.get("lot_size")) or 0 or None

        display_name = (raw.get("name") or "").strip() or None

        identifiers: list[IdentifierRecord] = [
            IdentifierRecord(
                identifier_type="VENUE_SYMBOL",
                identifier_value=canonical_symbol,
                venue_code=venue,
            ),
            IdentifierRecord(
                identifier_type="BROKER_SYMBOL",
                identifier_value=canonical_symbol,
                broker_code=self.broker_code,
                venue_code=venue,
            ),
        ]
        if external_token is not None:
            identifiers.append(
                IdentifierRecord(
                    identifier_type="BROKER_TOKEN",
                    identifier_value=external_token,
                    broker_code=self.broker_code,
                    venue_code=venue,
                )
            )

        return NormalizedInstrumentRow(
            venue_code=venue,
            market_family="IN_STOCK",
            venue_timezone=self.venue_timezone,
            canonical_symbol=canonical_symbol,
            asset_class=asset_class,
            instrument_kind=instrument_kind,
            external_symbol=external_symbol,
            external_token=external_token,
            tick_size=tick_size,
            lot_size=lot_size,
            expiration_at=expiry,
            option_right=option_right,
            strike=strike,
            currency="INR",
            display_name=display_name,
            identifiers=identifiers,
        )

    # ------------------------------------------------------------------
    # Protocol: resolve_venue / resolve_identifiers
    # These are thin passthroughs because `normalize` already does the work.

    def resolve_venue(self, normalized: NormalizedInstrumentRow) -> str:
        return normalized.venue_code

    def resolve_identifiers(
        self, normalized: NormalizedInstrumentRow
    ) -> list[IdentifierRecord]:
        return list(normalized.identifiers)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _classify(
    inst_type: str, venue: str
) -> tuple[Optional[str], Optional[str], Optional[str]]:
    """Return (asset_class, instrument_kind, option_right)."""
    if venue.endswith("_INDEX"):
        return "INDEX", "CASH", None
    if inst_type == "EQ":
        return "EQUITY", "CASH", None
    if inst_type == "FUT":
        return "FUTURE", "DERIVATIVE", None
    if inst_type == "CE":
        return "OPTION", "DERIVATIVE", "CALL"
    if inst_type == "PE":
        return "OPTION", "DERIVATIVE", "PUT"
    return None, None, None


def _parse_kite_expiry(value: Any) -> Optional[datetime]:
    """Kite expiry is `YYYY-MM-DD` (or empty for cash)."""
    if value is None:
        return None
    raw = str(value).strip()
    if not raw:
        return None
    try:
        return datetime.strptime(raw, "%Y-%m-%d").replace(tzinfo=timezone.utc)
    except ValueError:
        return None


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


__all__ = ["ZerodhaAdapter"]
