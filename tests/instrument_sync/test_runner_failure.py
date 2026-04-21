"""Runner failure semantics.

If `fetch_raw` raises mid-stream, the current sync is marked `failed`
but any broker-map rows inserted in already-committed chunks stay
present under that sync_version. The NEXT successful sync at a higher
sync_version is what soft-prunes them.
"""

from __future__ import annotations

from typing import Iterable

import pytest

from database.instruments_repo import (
    broker_map_lookup_by_symbol,
    sync_run_latest,
)
from services.instrument_sync_service import (
    IdentifierRecord,
    InstrumentSyncRunner,
    NormalizedInstrumentRow,
    RawInstrumentRow,
)


class _ExplodingAdapter:
    """Yields two good rows, then raises."""

    broker_code = "test_explode"

    def fetch_raw(self) -> Iterable[RawInstrumentRow]:
        yield {"n": 1}
        yield {"n": 2}
        raise RuntimeError("simulated network failure mid-sync")

    def normalize(self, raw: RawInstrumentRow):
        n = raw["n"]
        return NormalizedInstrumentRow(
            venue_code="NSE",
            market_family="IN_STOCK",
            venue_timezone="Asia/Kolkata",
            canonical_symbol=f"EXPLODE{n}",
            asset_class="EQUITY",
            instrument_kind="CASH",
            external_symbol=f"EXPLODE{n}",
            external_token=f"T{n}",
            identifiers=[
                IdentifierRecord("VENUE_SYMBOL", f"EXPLODE{n}", venue_code="NSE")
            ],
        )

    def resolve_venue(self, norm: NormalizedInstrumentRow) -> str:
        return norm.venue_code

    def resolve_identifiers(
        self, norm: NormalizedInstrumentRow
    ) -> list[IdentifierRecord]:
        return norm.identifiers


def test_mid_stream_failure_marks_sync_failed(fresh_db) -> None:
    """Only 2 rows were yielded before the raise — and the chunk-size
    is 500, so the chunk never committed. The sync_run is marked failed
    and the broker_instrument_map has no rows from this attempt."""
    with pytest.raises(RuntimeError, match="simulated network failure"):
        InstrumentSyncRunner().run(_ExplodingAdapter())

    latest = sync_run_latest("test_explode")
    assert latest is not None
    assert latest.status == "failed"
    assert "simulated network failure" in (latest.error or "")

    # No rows committed because the single open chunk never flushed.
    assert broker_map_lookup_by_symbol("test_explode", "NSE", "EXPLODE1") is None


def test_previous_successful_sync_survives_a_failed_one(fresh_db) -> None:
    """Two sync runs — the first succeeds with a good adapter, the second
    fails midway. The first run's broker-map rows must still be present
    (they carry the older sync_version)."""
    # Run 1 — success
    class _GoodAdapter:
        broker_code = "test_good"

        def fetch_raw(self):
            yield {"n": 1}

        def normalize(self, raw):
            return NormalizedInstrumentRow(
                venue_code="NSE",
                market_family="IN_STOCK",
                venue_timezone="Asia/Kolkata",
                canonical_symbol="GOOD1",
                asset_class="EQUITY",
                instrument_kind="CASH",
                external_symbol="GOOD1",
                external_token="G1",
                identifiers=[
                    IdentifierRecord("VENUE_SYMBOL", "GOOD1", venue_code="NSE")
                ],
            )

        def resolve_venue(self, norm):
            return norm.venue_code

        def resolve_identifiers(self, norm):
            return norm.identifiers

    InstrumentSyncRunner().run(_GoodAdapter())

    # Run 2 — failure (different broker_code to isolate, so no soft-prune
    # of the successful rows happens)
    with pytest.raises(RuntimeError):
        InstrumentSyncRunner().run(_ExplodingAdapter())

    # The original row is still there and reachable.
    assert broker_map_lookup_by_symbol("test_good", "NSE", "GOOD1") is not None
