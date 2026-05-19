#!/usr/bin/env python3
"""Bowaka v2 — minimal operator dashboard.

Read-only CLI: prints live candidate events (last 20), accepted vs
rejected today (with reasons), open positions w/ unrealized PnL,
gross exposure %, daily realized PnL, kill-switch state, scanner
last_run_ts age.
"""
from __future__ import annotations

import argparse
import json
import logging
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

_SCRIPT_DIR = Path(__file__).resolve().parent
if str(_SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPT_DIR))

import bowaka_v2_paths as paths  # noqa: E402


LOG = logging.getLogger("bowaka_v2_dashboard")


def _load_jsonl_tail(p: Path, n: int = 20) -> list[dict]:
    if not p.exists():
        return []
    lines = p.read_text(encoding="utf-8").splitlines()
    out = []
    for raw in lines[-n:]:
        raw = raw.strip()
        if not raw:
            continue
        try:
            out.append(json.loads(raw))
        except ValueError:
            pass
    return out


def _load_json(p: Path) -> dict:
    if not p.exists():
        return {}
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return {}


def build_dashboard_snapshot(
    today_iso: str | None = None,
    *,
    state_path: Path | None = None,
    candidates_path: Path | None = None,
    decisions_path: Path | None = None,
    heartbeat_path: Path | None = None,
    kill_flag_dir: Path | None = None,
) -> dict:
    today_iso = today_iso or datetime.now(timezone.utc).date().isoformat()
    state = _load_json(state_path or paths.V2_STATE_PATH)
    candidates = _load_jsonl_tail(candidates_path or paths.CANDIDATE_EVENTS_PATH)
    decisions = _load_jsonl_tail(
        decisions_path or paths.ENTRY_DECISIONS_PATH, n=200,
    )
    today_decisions = [
        d for d in decisions if d.get("session_date") == today_iso
    ]
    accepted = [d for d in today_decisions if d.get("decision") == "accepted"]
    rejected = [d for d in today_decisions if d.get("decision") == "rejected"]
    rej_reasons = Counter(d.get("reason", "?") for d in rejected)

    hb_path = heartbeat_path or paths.SCANNER_HEARTBEAT_PATH
    hb_age = None
    if hb_path.exists():
        try:
            hb_age = (
                datetime.now(timezone.utc).timestamp()
                - hb_path.stat().st_mtime
            )
        except Exception:
            pass

    kill_dir = kill_flag_dir or paths.REPO_ROOT
    kill_flags = {
        "L1_KILL_NEW": (kill_dir / "KILL_NEW.flag").exists(),
        "L2_KILL_SOFT": (kill_dir / "KILL_SOFT.flag").exists(),
        "L3_KILL_HARD": (kill_dir / "KILL_HARD.flag").exists(),
    }

    return {
        "today": today_iso,
        "scanner_heartbeat_age_seconds": hb_age,
        "recent_candidates": [
            {"symbol": c.get("symbol"), "ts": c.get("scan_timestamp")}
            for c in candidates
        ],
        "decisions_today": {
            "accepted": len(accepted),
            "rejected": len(rejected),
            "rejection_breakdown": dict(rej_reasons),
        },
        "open_positions_count": len(state.get("open_positions") or {}),
        "gross_exposure_dollars": float(
            state.get("gross_exposure_dollars", 0.0),
        ),
        "daily_realized_pnl": float(
            state.get("daily_realized_pnl_strategy", 0.0),
        ),
        "kill_flags": kill_flags,
    }


def render(snapshot: dict) -> str:
    lines = []
    lines.append(f"=== Bowaka v2 Dashboard — {snapshot['today']} ===")
    hb = snapshot.get("scanner_heartbeat_age_seconds")
    lines.append(
        f"scanner heartbeat age: "
        f"{f'{hb:.1f}s' if hb is not None else 'n/a'}"
    )
    d = snapshot["decisions_today"]
    lines.append(
        f"decisions today: accepted={d['accepted']} rejected={d['rejected']}"
    )
    for r, n in d["rejection_breakdown"].items():
        lines.append(f"  rejected/{r}: {n}")
    lines.append(
        f"open positions: {snapshot['open_positions_count']}"
    )
    lines.append(
        f"gross exposure $: {snapshot['gross_exposure_dollars']:.2f}"
    )
    lines.append(
        f"daily realized PnL: ${snapshot['daily_realized_pnl']:.2f}"
    )
    for k, v in snapshot["kill_flags"].items():
        lines.append(f"  {k}: {'SET' if v else '-'}")
    lines.append("recent candidates (last 20):")
    for c in snapshot["recent_candidates"][-20:]:
        lines.append(f"  {c['ts']}  {c['symbol']}")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Bowaka v2 dashboard")
    parser.add_argument("--once", action="store_true",
                        help="Render once and exit.")
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO)
    snap = build_dashboard_snapshot()
    print(render(snap))
    return 0


if __name__ == "__main__":
    sys.exit(main())
