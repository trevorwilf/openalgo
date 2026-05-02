"""Phase 2-bis-2 (T-15) — backfill SandboxFunds.total_capital +
available_balance NULLs.

The Phase 2-bis-2 commit removed the schema-level ``default=10000000.00``
on ``SandboxFunds.total_capital`` and ``available_balance`` so non-
India deployments don't get silently nudged into an INR-shaped
capital. The active sandbox provider seeds the value on row
creation (``IndiaSandboxProvider.initial_funds()``,
``USSandboxProvider.initial_funds()``, etc.).

Existing rows in deployed India sandboxes were inserted with the
legacy ₹1Cr default. This migration backfills any NULL
total_capital / available_balance values with the legacy
``Decimal("10000000.00")`` value to preserve India parity.

Idempotent: rows that already have a non-NULL value are left alone.

Usage::

    uv run python upgrade/migrate_sandbox_funds_starting_capital_default.py
"""

from __future__ import annotations

import sys
from decimal import Decimal
from pathlib import Path

# Ensure repo root on sys.path so the migration can import directly.
_REPO_ROOT = Path(__file__).resolve().parents[1]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))


_LEGACY_INDIA_CAPITAL = Decimal("10000000.00")  # ₹1 Crore


def _backfill_nulls() -> int:
    """Backfill NULLs and return the count of rows updated."""
    from database.sandbox_db import SandboxFunds, db_session

    rows = SandboxFunds.query.filter(
        (SandboxFunds.total_capital.is_(None))
        | (SandboxFunds.available_balance.is_(None))
    ).all()

    updated = 0
    for row in rows:
        if row.total_capital is None:
            row.total_capital = _LEGACY_INDIA_CAPITAL
        if row.available_balance is None:
            row.available_balance = _LEGACY_INDIA_CAPITAL
        updated += 1

    if updated:
        db_session.commit()
    return updated


def main() -> int:
    try:
        # Force the sandbox DB engine to initialize.
        from database.sandbox_db import init_db

        init_db()
    except Exception as exc:
        print(f"FATAL: sandbox DB unavailable: {exc}", file=sys.stderr)
        return 2
    try:
        n = _backfill_nulls()
    except Exception as exc:
        print(f"FATAL: backfill failed: {exc}", file=sys.stderr)
        return 1
    if n:
        print(f"OK: backfilled {n} sandbox_funds rows with legacy ₹1Cr default")
    else:
        print("OK: no NULL sandbox_funds rows; nothing to backfill")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
