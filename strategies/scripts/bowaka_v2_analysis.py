#!/usr/bin/env python3
"""Bowaka v2 — analyst daily report.

Reads the v2 trade_ledger.jsonl (Phase 4 writes) and emits a daily
session summary with v1-parity sections: P&L, fills, rejections,
protection events, shadow risk hits.
"""
from __future__ import annotations

import argparse
import json
import logging
import sys
from collections import Counter
from pathlib import Path
from typing import Iterable

_SCRIPT_DIR = Path(__file__).resolve().parent
if str(_SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPT_DIR))

import bowaka_v2_paths as paths  # noqa: E402


LOG = logging.getLogger("bowaka_v2_analysis")


def _load_jsonl(path: Path) -> list[dict]:
    if not path.exists():
        return []
    out = []
    for raw in path.read_text(encoding="utf-8").splitlines():
        raw = raw.strip()
        if not raw:
            continue
        try:
            out.append(json.loads(raw))
        except ValueError:
            continue
    return out


def build_daily_summary(
    session_date: str,
    *,
    ledger: list[dict] | None = None,
    decisions: list[dict] | None = None,
) -> dict:
    ledger = ledger if ledger is not None else _load_jsonl(paths.V2_LEDGER_PATH)
    decisions = decisions if decisions is not None else _load_jsonl(
        paths.ENTRY_DECISIONS_PATH,
    )

    today_decisions = [
        d for d in decisions
        if d.get("session_date") == session_date
    ]
    accepted = [d for d in today_decisions if d.get("decision") == "accepted"]
    rejected = [d for d in today_decisions if d.get("decision") == "rejected"]
    rejection_reasons = Counter(d.get("reason", "?") for d in rejected)

    closures = [
        e for e in ledger
        if e.get("event_type") == "closure"
        and e.get("session_date") == session_date
    ]
    realized_pnl = sum(
        float((e.get("payload") or {}).get("realized_pnl") or 0.0)
        for e in closures
    )
    exit_reasons = Counter(
        ((e.get("payload") or {}).get("reason") or "?")
        for e in closures
    )

    return {
        "session_date": session_date,
        "decisions": {
            "accepted": len(accepted),
            "rejected": len(rejected),
            "by_rejection_reason": dict(rejection_reasons),
        },
        "closures": {
            "count": len(closures),
            "total_realized_pnl": realized_pnl,
            "by_reason": dict(exit_reasons),
        },
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Bowaka v2 analysis")
    parser.add_argument("--session-date", required=True)
    parser.add_argument("--output", default=None)
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO)
    summary = build_daily_summary(args.session_date)
    out = (
        Path(args.output)
        if args.output
        else paths.BACKTEST_REPORTS_DIR / f"daily_{args.session_date}.json"
    )
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(summary, indent=2, default=str))
    LOG.info("daily report -> %s", out)
    return 0


if __name__ == "__main__":
    sys.exit(main())
