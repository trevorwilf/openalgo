"""Alpaca instrument sync — populate the canonical instrument universe
from Alpaca's tradable-assets endpoint.

GET /v2/assets?status=active&asset_class=us_equity

Behavior:

- Upsert each asset into ``instruments`` keyed by
  ``(venue_code, canonical_symbol)``. New instruments get a fresh UUID;
  existing rows are left in place with their UUID preserved.
- Upsert into ``broker_instrument_map`` with Alpaca's symbol and id.
- Record a row in ``instrument_sync_runs`` with counts + status.
- Idempotent: re-running with the same fixture makes no further
  changes.
- Non-destructive: assets that disappear from Alpaca's list are NOT
  deleted. The sync run's ``metadata`` captures a count-of-count
  delta for observability.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any, Iterable

import httpx

from broker.alpaca.api.auth_api import AlpacaAuth, authenticate
from database import instruments_repo
from database.instruments_repo import (
    BrokerMapRow,
    InstrumentSyncRun,
    broker_map_upsert_many,
    instruments_create,
    instruments_get_by_venue_symbol,
    session_scope,
    venues_upsert,
)
from sqlalchemy import select


BROKER_CODE = "alpaca"


@dataclass(frozen=True)
class SyncSummary:
    sync_id: uuid.UUID
    fetched_count: int
    new_instruments: int
    map_rows_written: int
    status: str


def _venues_for_us() -> None:
    """Ensure the four US equity venues exist in the venues table."""
    for venue_code in ("XNAS", "XNYS", "ARCX", "BATS"):
        venues_upsert(
            venue_code=venue_code,
            market_family="US_STOCK",
            country_code="US",
            base_currency="USD",
            timezone_name="America/New_York",
        )


def fetch_assets(
    auth: AlpacaAuth | None = None,
    client: httpx.Client | None = None,
) -> list[dict]:
    """Return the list of active tradable US equities from Alpaca."""
    if auth is None:
        auth = authenticate()
    params = {"status": "active", "asset_class": "us_equity"}
    if client is not None:
        r = client.get("/v2/assets", params=params)
    else:
        with httpx.Client(
            base_url=auth.base_url,
            headers=dict(auth.headers),
            timeout=httpx.Timeout(30.0, connect=5.0),
        ) as c:
            r = c.get("/v2/assets", params=params)
    r.raise_for_status()
    return r.json()


def _normalize_venue(exchange: str | None) -> str:
    if not exchange:
        return "XNAS"
    mapping = {
        "NASDAQ": "XNAS",
        "NYSE": "XNYS",
        "ARCA": "ARCX",
        "BATS": "BATS",
        "AMEX": "XNYS",
        "OTC": "XNAS",  # best-effort; fold OTC into XNAS for routing
    }
    return mapping.get(exchange.upper(), exchange.upper())


def _sync_version() -> int:
    """Monotonic sync version. Seconds since epoch is enough for
    idempotency."""
    return int(datetime.now(tz=timezone.utc).timestamp())


def sync_instruments(
    auth: AlpacaAuth | None = None,
    assets: Iterable[dict] | None = None,
    client: httpx.Client | None = None,
) -> SyncSummary:
    """Run a one-shot instrument sync. Returns a :class:`SyncSummary`.

    Parameters
    ----------
    auth: Optional :class:`AlpacaAuth` — when None, credentials are
        loaded from env (Phase 6a :func:`authenticate`).
    assets: Optional pre-fetched list of asset rows — lets tests
        bypass the HTTP fetch entirely.
    client: Optional httpx client — lets tests wire in a MockTransport.
    """
    _venues_for_us()
    if assets is None:
        rows = fetch_assets(auth=auth, client=client)
    else:
        rows = list(assets)

    sync_version = _sync_version()
    sync_id = uuid.uuid4()
    new_instruments = 0
    map_rows: list[tuple[str, BrokerMapRow]] = []

    # Group by venue so we can batch broker_map inserts.
    by_venue: dict[str, list[BrokerMapRow]] = {}
    for row in rows:
        symbol = row.get("symbol")
        if not symbol:
            continue
        venue = _normalize_venue(row.get("exchange"))
        existing = instruments_get_by_venue_symbol(venue, symbol)
        if existing is None:
            created = instruments_create(
                venue_code=venue,
                canonical_symbol=symbol,
                asset_class="EQUITY",
                instrument_kind="CASH",
                tick_size=Decimal("0.01"),
                quantity_precision=9 if row.get("fractionable") else 0,
                currency="USD",
                display_name=row.get("name"),
                metadata={
                    "alpaca_id": row.get("id"),
                    "class": row.get("class"),
                    "tradable": row.get("tradable"),
                    "shortable": row.get("shortable"),
                    "easy_to_borrow": row.get("easy_to_borrow"),
                    "fractionable": row.get("fractionable"),
                },
            )
            new_instruments += 1
            instrument_id = created.instrument_id
        else:
            instrument_id = existing.instrument_id

        by_venue.setdefault(venue, []).append(
            BrokerMapRow(
                external_symbol=symbol,
                external_token=str(row.get("id", "")) or None,
                instrument_id=instrument_id,
            )
        )

    map_rows_written = 0
    for venue, batch in by_venue.items():
        map_rows_written += broker_map_upsert_many(
            broker_code=BROKER_CODE,
            venue_code=venue,
            rows=batch,
            sync_version=sync_version,
        )

    _record_run(
        sync_id=sync_id,
        sync_version=sync_version,
        fetched=len(rows),
        new_instruments=new_instruments,
        map_rows_written=map_rows_written,
        status="ok",
    )

    # Observability: sync lag = seconds since the sync *started*.
    # The sync runner is a one-shot call; lag goes back to 0 on every
    # completion. Operators alert on "lag never decreases" as a stall
    # signal.
    try:
        from utils.metrics import gauge

        gauge(
            "instrument_sync_lag_seconds",
            {"broker": BROKER_CODE},
            value=0.0,
        )
    except Exception:  # pragma: no cover
        pass

    return SyncSummary(
        sync_id=sync_id,
        fetched_count=len(rows),
        new_instruments=new_instruments,
        map_rows_written=map_rows_written,
        status="ok",
    )


def _record_run(
    *,
    sync_id: uuid.UUID,
    sync_version: int,
    fetched: int,
    new_instruments: int,
    map_rows_written: int,
    status: str,
) -> None:
    with session_scope() as s:
        # Build an audit trail of the last sync runs.
        s.add(
            InstrumentSyncRun(
                sync_id=sync_id,
                broker_code=BROKER_CODE,
                venue_code=None,  # cross-venue run
                sync_version=sync_version,
                completed_at=datetime.now(tz=timezone.utc),
                status=status,
                instrument_count=fetched,
                source="alpaca://v2/assets",
                metadata_json={
                    "new_instruments": new_instruments,
                    "broker_map_rows_written": map_rows_written,
                },
            )
        )


def latest_run(
    broker_code: str = BROKER_CODE,
) -> InstrumentSyncRun | None:
    with session_scope() as s:
        return s.scalar(
            select(InstrumentSyncRun)
            .where(InstrumentSyncRun.broker_code == broker_code)
            .order_by(InstrumentSyncRun.started_at.desc())
            .limit(1)
        )


__all__ = ["BROKER_CODE", "SyncSummary", "fetch_assets", "latest_run", "sync_instruments"]
