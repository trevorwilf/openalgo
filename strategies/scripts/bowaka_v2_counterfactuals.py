#!/usr/bin/env python3
"""Bowaka v2 — counterfactual reports.

Reads v2's per-session counterfactual streams (counterfactual_
entries.jsonl, counterfactual_exits.jsonl, entry_decisions.jsonl,
trade_ledger.jsonl) and produces per-trade analysis reports under
``data/bowaka_v2/counterfactual_reports/<session>/``.

Maintains feature parity with v1's bowaka_counterfactuals.py
(captured under tests/strategies/fixtures/v1_golden/).
"""
from __future__ import annotations

import argparse
import json
import logging
import sys
from collections import defaultdict
from pathlib import Path
from typing import Iterable

_SCRIPT_DIR = Path(__file__).resolve().parent
if str(_SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPT_DIR))

import bowaka_v2_paths as paths  # noqa: E402


LOG = logging.getLogger("bowaka_v2_counterfactuals")


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


def build_report(
    *,
    counterfactual_entries: list[dict],
    counterfactual_exits: list[dict],
    entry_decisions: list[dict],
    trade_ledger: list[dict],
    session_date: str,
) -> dict:
    """Produce a per-session counterfactual report.

    Schema:
      {
        session_date,
        accepted_entries: int,
        rejected_entries: int,
        alt_order_style_deltas: [{symbol, pnl_delta}],
        delayed_entry_deltas: [{symbol, delay, pnl_delta}],
        signal_fade_variant_deltas: [{symbol, pnl_delta}],
      }
    """
    accepted = [
        d for d in entry_decisions
        if d.get("decision") == "accepted"
        and d.get("session_date") == session_date
    ]
    rejected = [
        d for d in entry_decisions
        if d.get("decision") == "rejected"
        and d.get("session_date") == session_date
    ]

    alt_order_deltas = []
    for cf in counterfactual_entries:
        if cf.get("session_date") and cf["session_date"] != session_date:
            continue
        if cf.get("order_style"):
            alt_order_deltas.append({
                "symbol": cf.get("symbol"),
                "order_style": cf.get("order_style"),
                "pnl_delta": cf.get("hypothetical_pnl_delta", 0.0),
            })

    delayed_deltas = [
        {"symbol": cf.get("symbol"),
         "delay": cf.get("delay_minutes"),
         "pnl_delta": cf.get("hypothetical_pnl_delta", 0.0)}
        for cf in counterfactual_entries
        if cf.get("delay_minutes")
    ]
    signal_fade_deltas = [
        {"symbol": cf.get("symbol"),
         "pnl_delta": cf.get("pnl_delta", 0.0)}
        for cf in counterfactual_exits
        if cf.get("variant") == "signal_fade_active"
    ]
    return {
        "session_date": session_date,
        "accepted_entries": len(accepted),
        "rejected_entries": len(rejected),
        "alt_order_style_deltas": alt_order_deltas,
        "delayed_entry_deltas": delayed_deltas,
        "signal_fade_variant_deltas": signal_fade_deltas,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Bowaka v2 counterfactual reports",
    )
    parser.add_argument(
        "--session-date", required=True,
        help="YYYY-MM-DD to process",
    )
    parser.add_argument("--output-dir", default=None)
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO)

    entries = _load_jsonl(paths.COUNTERFACTUAL_ENTRIES_PATH)
    exits = _load_jsonl(paths.COUNTERFACTUAL_EXITS_PATH)
    decisions = _load_jsonl(paths.ENTRY_DECISIONS_PATH)
    ledger = _load_jsonl(paths.V2_LEDGER_PATH)

    report = build_report(
        counterfactual_entries=entries,
        counterfactual_exits=exits,
        entry_decisions=decisions,
        trade_ledger=ledger,
        session_date=args.session_date,
    )
    out_dir = Path(args.output_dir) if args.output_dir else (
        paths.COUNTERFACTUAL_REPORTS_DIR / args.session_date
    )
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "report.json").write_text(
        json.dumps(report, indent=2, default=str)
    )
    LOG.info(
        "counterfactual report for %s: accepted=%d rejected=%d "
        "alt-order=%d delayed=%d signal-fade=%d",
        args.session_date, report["accepted_entries"],
        report["rejected_entries"],
        len(report["alt_order_style_deltas"]),
        len(report["delayed_entry_deltas"]),
        len(report["signal_fade_variant_deltas"]),
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
