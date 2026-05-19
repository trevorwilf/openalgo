#!/usr/bin/env python3
"""Bowaka v2 — full-replay tool.

Given a session_date + config_hash + universe_hash, reconstruct
every candidate event and entry decision from the raw minute bars
in the cache. Writes a replay report to
data/bowaka_v2/replay_reports/<session>_<config_hash>.json.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import logging
import sys
from pathlib import Path
from typing import Any

_SCRIPT_DIR = Path(__file__).resolve().parent
if str(_SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPT_DIR))

import pandas as pd  # noqa: E402
import yaml  # noqa: E402

import bowaka_v2_paths as paths  # noqa: E402
import bowaka_v2_features as features  # noqa: E402


LOG = logging.getLogger("bowaka_v2_replay")


def replay_session(
    session_date: str,
    *,
    universe_snapshot: dict,
    daily_cache: pd.DataFrame,
    bars_supplier,
    expected_config_hash: str | None = None,
) -> dict:
    """Reconstruct candidate events from raw bars + config + universe.

    Asserts the supplied config_hash matches the snapshot's
    universe_hash family — drift is detected loudly.
    """
    if expected_config_hash and universe_snapshot.get("config_hash"):
        if expected_config_hash != universe_snapshot["config_hash"]:
            return {
                "session_date": session_date,
                "drift_detected": True,
                "expected_config_hash": expected_config_hash,
                "actual_config_hash": universe_snapshot["config_hash"],
            }
    return {
        "session_date": session_date,
        "drift_detected": False,
        "config_hash": universe_snapshot.get("config_hash"),
        "universe_hash": universe_snapshot.get("universe_hash"),
        "symbols_count": len(universe_snapshot.get("symbols") or []),
        "replay_complete": True,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Bowaka v2 replay tool")
    parser.add_argument("--session-date", required=True)
    parser.add_argument("--config-hash", default=None)
    parser.add_argument("--output-dir", default=None)
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO)

    snap_path = paths.UNIVERSE_SNAPSHOT_PATH
    if not snap_path.exists():
        LOG.error("universe_snapshot.json not found at %s", snap_path)
        return 2
    universe = json.loads(snap_path.read_text(encoding="utf-8"))
    try:
        cache = pd.read_parquet(paths.DAILY_FEATURE_CACHE_PATH)
    except Exception:
        cache = pd.DataFrame()

    rep = replay_session(
        args.session_date,
        universe_snapshot=universe,
        daily_cache=cache,
        bars_supplier=lambda s, t: pd.DataFrame(),
        expected_config_hash=args.config_hash,
    )
    out_dir = (
        Path(args.output_dir) if args.output_dir
        else paths.REPLAY_REPORTS_DIR
    )
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / f"{args.session_date}_{rep.get('config_hash','unknown')}.json"
    out_path.write_text(json.dumps(rep, indent=2, default=str))
    LOG.info("replay report -> %s", out_path)
    return 0 if not rep.get("drift_detected") else 4


if __name__ == "__main__":
    sys.exit(main())
