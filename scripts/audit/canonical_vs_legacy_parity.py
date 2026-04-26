"""Phase 3 v3 / ADR 0019 — measure canonical-resolver vs legacy-SymToken
parity for the India broker fixtures used by the parity harness.

For each fixture in ``tests/parity/baseline/``, the script reads the
canonical resolver's view of the named instrument and the legacy
``database.symbol.SymToken`` view, then writes a diff report to
``docs/refactor/canonical_legacy_parity_report.md``.

This is the **measurement** tool — the actual migration of India
traffic to the canonical resolver is a future operator-controlled
phase, gated on the report showing zero diffs. Differences logged
here today are not failures; they are the to-do list.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[2]
BASELINE_DIR = REPO_ROOT / "tests" / "parity" / "baseline"
OUTPUT = REPO_ROOT / "docs" / "refactor" / "canonical_legacy_parity_report.md"


def _gather_fixture_pairs() -> list[tuple[str, str]]:
    """Return a list of (symbol, exchange) pairs from the parity fixtures.

    Walks the JSON files under ``tests/parity/baseline/`` and pulls
    out every (symbol, exchange) pair we can find in the request
    bodies. Pairs are de-duplicated.
    """
    pairs: set[tuple[str, str]] = set()
    if not BASELINE_DIR.is_dir():
        return []
    for path in BASELINE_DIR.rglob("*.json"):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        _walk(data, pairs)
    return sorted(pairs)


def _walk(node: Any, pairs: set[tuple[str, str]]) -> None:
    if isinstance(node, dict):
        sym = node.get("symbol") or node.get("canonical_symbol")
        exch = node.get("exchange") or node.get("venue_code")
        if isinstance(sym, str) and isinstance(exch, str):
            pairs.add((sym, exch))
        for v in node.values():
            _walk(v, pairs)
    elif isinstance(node, list):
        for v in node:
            _walk(v, pairs)


def _legacy_view(symbol: str, exchange: str) -> dict | None:
    """Return the legacy SymToken row's projection, or None when the
    legacy DB is unavailable.

    This deliberately tolerates a missing/unfilled legacy DB so the
    script can run in a fresh dev environment.
    """
    try:
        from database.symbol import SymToken, db_session
    except Exception:
        return None
    try:
        with db_session() as s:
            row = (
                s.query(SymToken)
                .filter(SymToken.symbol == symbol, SymToken.exchange == exchange)
                .first()
            )
            if row is None:
                return None
            return {
                "symbol": row.symbol,
                "brsymbol": row.brsymbol,
                "exchange": row.exchange,
                "brexchange": row.brexchange,
                "token": row.token,
                "lotsize": row.lotsize,
                "instrumenttype": row.instrumenttype,
                "tick_size": float(row.tick_size) if row.tick_size is not None else None,
            }
    except Exception:
        return None


def _canonical_view(symbol: str, exchange: str) -> dict | None:
    """Return the canonical Instrument row's projection."""
    try:
        from database.instruments_repo import instruments_get_by_venue_symbol
    except Exception:
        return None
    try:
        row = instruments_get_by_venue_symbol(exchange, symbol)
    except Exception:
        return None
    if row is None:
        return None
    return {
        "venue_code": row.venue_code,
        "canonical_symbol": row.canonical_symbol,
        "asset_class": row.asset_class,
        "instrument_kind": row.instrument_kind,
        "lot_size": row.lot_size,
        "tick_size": float(row.tick_size) if row.tick_size is not None else None,
        "currency": row.currency,
    }


def _diff(legacy: dict | None, canonical: dict | None) -> str:
    if legacy is None and canonical is None:
        return "both_missing"
    if legacy is None:
        return "legacy_missing_canonical_present"
    if canonical is None:
        return "canonical_missing_legacy_present"
    diffs: list[str] = []
    if legacy.get("brsymbol") and canonical.get("canonical_symbol") != legacy.get("symbol"):
        diffs.append("symbol_mismatch")
    if legacy.get("lotsize") and canonical.get("lot_size") != legacy.get("lotsize"):
        diffs.append("lot_size_mismatch")
    if legacy.get("tick_size") and canonical.get("tick_size") != legacy.get("tick_size"):
        diffs.append("tick_size_mismatch")
    return "match" if not diffs else "; ".join(diffs)


def main() -> int:
    pairs = _gather_fixture_pairs()
    rows: list[dict[str, Any]] = []
    for symbol, exchange in pairs:
        legacy = _legacy_view(symbol, exchange)
        canonical = _canonical_view(symbol, exchange)
        rows.append({
            "symbol": symbol,
            "exchange": exchange,
            "result": _diff(legacy, canonical),
            "legacy_present": legacy is not None,
            "canonical_present": canonical is not None,
        })
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    lines = [
        "# Canonical resolver vs legacy SymToken — India parity measurement",
        "",
        "Generated by `scripts/audit/canonical_vs_legacy_parity.py`. Each",
        "row pairs an India-fixture (symbol, exchange) with its legacy",
        "SymToken row and its canonical Instrument row, and reports the",
        "diff. India migration to the canonical resolver is gated on this",
        "report showing zero `*_mismatch` rows.",
        "",
        f"Pairs sampled from `tests/parity/baseline/`: **{len(rows)}**.",
        "",
        "| symbol | exchange | result | legacy_present | canonical_present |",
        "|---|---|---|---|---|",
    ]
    for r in rows:
        lines.append(
            "| `{sym}` | `{ex}` | {res} | {lp} | {cp} |".format(
                sym=r["symbol"], ex=r["exchange"], res=r["result"],
                lp="yes" if r["legacy_present"] else "no",
                cp="yes" if r["canonical_present"] else "no",
            )
        )
    if not rows:
        lines.append("| — | — | no_pairs_in_baseline | no | no |")
    OUTPUT.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"Wrote {OUTPUT.relative_to(REPO_ROOT)} ({len(rows)} pairs)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
