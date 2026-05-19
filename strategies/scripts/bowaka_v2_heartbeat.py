#!/usr/bin/env python3
"""Bowaka v2 — heartbeat monitor.

Reads scanner_heartbeat.jsonl (and optionally broker poll events)
and, if neither emits for > stale_threshold_seconds, writes the
KILL_NEW.flag file so the strategy's L1 kill switch fires.
"""
from __future__ import annotations

import argparse
import json
import logging
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

_SCRIPT_DIR = Path(__file__).resolve().parent
if str(_SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPT_DIR))

import bowaka_v2_paths as paths  # noqa: E402


LOG = logging.getLogger("bowaka_v2_heartbeat")


def _last_heartbeat_age(p: Path, now_utc: datetime) -> float | None:
    """Return seconds since the last heartbeat line was written
    (best-effort: uses file mtime if line parsing fails)."""
    if not p.exists():
        return None
    try:
        last = None
        for raw in p.read_text(encoding="utf-8").splitlines():
            raw = raw.strip()
            if not raw:
                continue
            try:
                ev = json.loads(raw)
            except ValueError:
                continue
            last = ev.get("ts") or ev.get("last_run_ts")
        if last:
            ts = datetime.fromisoformat(last.replace("Z", "+00:00"))
            if ts.tzinfo is None:
                ts = ts.replace(tzinfo=timezone.utc)
            return (now_utc - ts).total_seconds()
    except Exception:
        pass
    # Fall back to mtime.
    return now_utc.timestamp() - p.stat().st_mtime


def check_and_kill(
    heartbeat_path: Path,
    kill_flag_path: Path,
    *,
    stale_threshold_seconds: float = 60.0,
    now_utc: datetime | None = None,
) -> dict:
    """One-shot heartbeat check. Returns the diagnostic dict;
    writes KILL_NEW.flag when the scanner is stale."""
    now = now_utc or datetime.now(timezone.utc)
    age = _last_heartbeat_age(heartbeat_path, now)
    payload = {
        "checked_at": now.isoformat(),
        "heartbeat_age_seconds": age,
        "stale_threshold_seconds": stale_threshold_seconds,
        "kill_flag_written": False,
    }
    if age is None or age > stale_threshold_seconds:
        kill_flag_path.parent.mkdir(parents=True, exist_ok=True)
        kill_flag_path.write_text(
            json.dumps({
                "source": "bowaka_v2_heartbeat",
                "reason": "scanner_stale",
                "age_seconds": age,
                "threshold": stale_threshold_seconds,
                "at": now.isoformat(),
            }),
        )
        payload["kill_flag_written"] = True
    return payload


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Bowaka v2 heartbeat monitor",
    )
    parser.add_argument("--heartbeat-path", default=None)
    parser.add_argument("--kill-flag", default=None)
    parser.add_argument("--threshold-seconds", type=float, default=60.0)
    parser.add_argument(
        "--once", action="store_true",
        help="Run a single check and exit (CI / smoke).",
    )
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO)
    hb = Path(args.heartbeat_path) if args.heartbeat_path else paths.SCANNER_HEARTBEAT_PATH
    kf = Path(args.kill_flag) if args.kill_flag else (paths.REPO_ROOT / "KILL_NEW.flag")
    result = check_and_kill(
        hb, kf, stale_threshold_seconds=args.threshold_seconds,
    )
    LOG.info("heartbeat check: %s", result)
    return 0


if __name__ == "__main__":
    sys.exit(main())
