"""Mock Schwab-LIKE instrument sync — 5 deterministic US instruments."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any

BROKER_CODE = "_mock_schwab_like"

INSTRUMENTS = [
    ("AAPL", "Apple Inc."),
    ("MSFT", "Microsoft Corp."),
    ("SPY", "SPDR S&P 500 ETF"),
    ("QQQ", "Invesco QQQ Trust"),
    ("NVDA", "NVIDIA Corp."),
]


def run_sync() -> dict[str, Any]:
    """Idempotent: insert 5 instruments + broker_instrument_map rows.

    Returns the sync provenance dict the framework records.
    """
    from database import instruments_repo

    instruments_repo.venues_upsert(
        venue_code="XNAS",
        market_family="US_STOCK",
        timezone_name="America/New_York",
        country_code="US",
        base_currency="USD",
    )
    sync_id = uuid.uuid4()
    rows: list[Any] = []
    for symbol, _name in INSTRUMENTS:
        inst = instruments_repo.instruments_create(
            venue_code="XNAS",
            canonical_symbol=symbol,
            asset_class="EQUITY",
            instrument_kind="EQUITY",
            tick_size=Decimal("0.01"),
            currency="USD",
        )
        rows.append(
            instruments_repo.BrokerMapRow(
                external_symbol=symbol,
                external_token=f"SCHWAB-{symbol}",
                instrument_id=inst.instrument_id,
            )
        )
    instruments_repo.broker_map_upsert_many(
        broker_code=BROKER_CODE,
        venue_code="XNAS",
        rows=rows,
        sync_version=int(datetime.now(timezone.utc).timestamp()),
    )
    return {
        "sync_id": str(sync_id),
        "broker_code": BROKER_CODE,
        "venue_code": "XNAS",
        "instruments_seeded": len(INSTRUMENTS),
        "completed_at": datetime.now(timezone.utc).isoformat(),
    }


__all__ = ["BROKER_CODE", "INSTRUMENTS", "run_sync"]
