#!/usr/bin/env python3
"""Phase 3b backfill — populate instrument_id on legacy historify rows.

MANUALLY INVOKED. Never run automatically. The assertion that a given
DuckDB's (symbol, exchange) rows came from a specific broker is the
operator's to make — historify carries no intrinsic broker provenance.

Typical workflow::

    # 1. Dry-run first (the default) to see what would change.
    uv run upgrade/backfill_historify_instrument_id.py \\
        --table market_data --broker-code zerodha

    # 2. Once the numbers look right, commit explicitly.
    uv run upgrade/backfill_historify_instrument_id.py \\
        --table market_data --broker-code zerodha --commit

Flags:
    --table         (required)  One of market_data, watchlist, data_catalog,
                                job_items, symbol_metadata.
    --broker-code   (required)  The broker whose data this DuckDB holds.
    --batch-size    (default 1000)
    --max-rows      (default unlimited) Safety ceiling in prod.
    --commit                    Explicit opt-in to WRITE. Absent → DRY RUN.

Counts are reported at the end: total rows visited, resolved, missed,
and duration. Resolver misses (no instrument in Phase 2a + no legacy
get_token hit) are non-fatal and logged at warn.
"""

from __future__ import annotations

import argparse
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dotenv import load_dotenv  # noqa: E402

env_path = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), ".env"
)
load_dotenv(env_path)

from utils.logging import get_logger  # noqa: E402

logger = get_logger(__name__)


ALLOWED_TABLES = frozenset(
    {"market_data", "watchlist", "data_catalog", "job_items", "symbol_metadata"}
)


# Tables with a single-column primary key we can UPDATE ... WHERE <pk> = ?.
# For market_data (composite PK) we UPDATE by the PK tuple. For others we
# look up by `id`.
_PK_COLUMNS: dict[str, tuple[str, ...]] = {
    "market_data": ("symbol", "exchange", "interval", "timestamp"),
    "watchlist": ("id",),
    "data_catalog": ("id",),
    "job_items": ("id",),
    "symbol_metadata": ("symbol", "exchange"),
}


def _pk_filter_clause(table: str) -> tuple[str, list[str]]:
    """Return (WHERE-clause, list-of-column-names) for PK-scoped UPDATE."""
    cols = _PK_COLUMNS[table]
    clause = " AND ".join(f"{c} = ?" for c in cols)
    return clause, list(cols)


def _iter_unresolved_rows(conn, table: str, batch_size: int, max_rows: int | None):
    """Yield (symbol, exchange, pk_values_tuple) for rows with NULL instrument_id."""
    cols = _PK_COLUMNS[table]
    select_cols = ["symbol", "exchange", *cols]
    # Deduplicate column names in case PK includes symbol/exchange.
    seen: list[str] = []
    for c in select_cols:
        if c not in seen:
            seen.append(c)
    select_list = ", ".join(seen)

    total_yielded = 0
    offset = 0
    while True:
        remaining = None if max_rows is None else (max_rows - total_yielded)
        if remaining is not None and remaining <= 0:
            return
        limit = batch_size if remaining is None else min(batch_size, remaining)
        rows = conn.execute(
            f"SELECT {select_list} FROM {table} "
            f"WHERE instrument_id IS NULL "
            f"ORDER BY {', '.join(cols)} "
            f"LIMIT {limit} OFFSET {offset}"
        ).fetchall()
        if not rows:
            return
        for row in rows:
            row_dict = dict(zip(seen, row))
            pk_vals = tuple(row_dict[c] for c in cols)
            yield row_dict["symbol"], row_dict["exchange"], pk_vals
            total_yielded += 1
        offset += len(rows)


def run_backfill(
    table: str,
    broker_code: str,
    batch_size: int,
    max_rows: int | None,
    commit: bool,
) -> dict[str, int]:
    from database.historify_db import get_connection
    from services.instrument_resolver import (
        ResolverAmbiguous,
        ResolverMiss,
        get_resolver,
    )

    clause, pk_cols = _pk_filter_clause(table)
    resolver = get_resolver()

    total = 0
    resolved = 0
    missed = 0
    start = time.monotonic()

    with get_connection() as conn:
        # Collect updates in-memory per batch so DuckDB sees them as a
        # single multi-statement transaction.
        batch_updates: list[tuple] = []
        for symbol, exchange, pk_vals in _iter_unresolved_rows(
            conn, table, batch_size, max_rows
        ):
            total += 1
            try:
                res = resolver.resolve_for_quote(
                    symbol=symbol, exchange=exchange, broker_code=broker_code
                )
                instrument_id = str(res.instrument_id)
                batch_updates.append((instrument_id, *pk_vals))
                resolved += 1
            except (ResolverMiss, ResolverAmbiguous) as e:
                missed += 1
                logger.warning(
                    "resolver miss for %s:%s (broker=%s): %s",
                    symbol, exchange, broker_code, e,
                )

            # Flush every batch_size rows
            if len(batch_updates) >= batch_size:
                if commit:
                    conn.executemany(
                        f"UPDATE {table} SET instrument_id = ? WHERE {clause}",
                        batch_updates,
                    )
                batch_updates.clear()

        # Final flush
        if batch_updates and commit:
            conn.executemany(
                f"UPDATE {table} SET instrument_id = ? WHERE {clause}",
                batch_updates,
            )

    duration = time.monotonic() - start
    return {
        "total": total,
        "resolved": resolved,
        "missed": missed,
        "duration_ms": int(duration * 1000),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--table", required=True, choices=sorted(ALLOWED_TABLES),
        help="Historify table to backfill.",
    )
    parser.add_argument(
        "--broker-code", required=True,
        help="Broker name whose data this DuckDB holds. See module docstring.",
    )
    parser.add_argument("--batch-size", type=int, default=1000)
    parser.add_argument(
        "--max-rows", type=int, default=None,
        help="Safety ceiling in prod. Omit for unlimited.",
    )
    parser.add_argument(
        "--commit", action="store_true",
        help="Explicit opt-in to WRITE. Absent means DRY RUN.",
    )
    args = parser.parse_args(argv)

    mode = "COMMITTING" if args.commit else "DRY RUN"
    print("=" * 70)
    print(f"Phase 3b historify instrument_id backfill — {mode}")
    print("=" * 70)
    print(f"  table:       {args.table}")
    print(f"  broker_code: {args.broker_code}")
    print(f"  batch_size:  {args.batch_size}")
    print(f"  max_rows:    {args.max_rows or 'unlimited'}")
    print()
    print("!! NOTE !! Historify data carries no intrinsic broker provenance.")
    print("!! Your --broker-code assertion drives every resolver call. !!")
    print()

    stats = run_backfill(
        table=args.table,
        broker_code=args.broker_code,
        batch_size=args.batch_size,
        max_rows=args.max_rows,
        commit=args.commit,
    )

    print("-" * 70)
    print(f"  total visited: {stats['total']}")
    print(f"  resolved:      {stats['resolved']}")
    print(f"  missed:        {stats['missed']}")
    print(f"  duration:      {stats['duration_ms']} ms")
    print("-" * 70)
    if not args.commit:
        print("DRY RUN — no rows were written. Re-run with --commit to apply.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
