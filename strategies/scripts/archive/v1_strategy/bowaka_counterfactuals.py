#!/usr/bin/env python3
"""Counterfactual entry & exit replay for Bowaka research.

Given a candidate, a minute-bar series, and a strategy config, this
module computes outcomes for a set of alternative entry timings and
exit surfaces without affecting live state. Output is one
``counterfactual_outcome`` record per (candidate, entry_scenario)
pair, written to data/<env>/counterfactuals/<YYYY-MM-DD>.jsonl.
"""
from __future__ import annotations

import argparse
import json
import math
import sys
from datetime import date as _date, datetime, time as _dtime, timezone
from pathlib import Path
from typing import Any, Iterable

# Allow CLI use without packaging.
_SCRIPT_DIR = Path(__file__).resolve().parent
if str(_SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPT_DIR))

import pandas as pd  # noqa: E402

import bowaka_strategy as bw  # noqa: E402


# Phase 7.3 — alternative entry timings. Each entry scenario maps to
# a function that picks the entry index in a minute-bar series.
ENTRY_SCENARIOS: list[str] = [
    "session_open_actual",
    "t_09_35",
    "t_09_40",
    "t_09_45",
    "t_10_00",
    "t_10_30",
    "or_breakout_15m",
    "vwap_reclaim_first",
    "vwap_pullback_after_breakout",
    "first_close_above_prior_close",
]


# Phase 7.3 — alternate exit surfaces. (name, stop_pct, target_pct,
# stop_management_rule). stop_management_rule is None for static
# bracket, otherwise a string label that downstream replay logic
# interprets ("breakeven_after_5_mfe", etc.).
EXIT_SURFACES: list[tuple[str, float, float, str | None]] = [
    ("stop_5_target_8",   0.05, 0.08, None),
    ("stop_5_target_15",  0.05, 0.15, None),
    ("stop_8_target_15",  0.08, 0.15, None),
    ("stop_10_target_20", 0.10, 0.20, None),
    ("breakeven_after_5_target_15",  0.08, 0.15, "breakeven_after_5_mfe"),
    ("lock_3_after_8_target_15",      0.08, 0.15, "lock_3_after_8_mfe"),
]


def _to_minute_dt(ts: Any) -> datetime | None:
    if ts is None:
        return None
    if isinstance(ts, datetime):
        return ts
    try:
        if isinstance(ts, str):
            return datetime.fromisoformat(ts.replace("Z", "+00:00"))
        return pd.to_datetime(ts).to_pydatetime()
    except Exception:
        return None


def _pick_entry_index(scenario: str, bars: pd.DataFrame) -> int | None:
    """Phase 7.3 — return the row index in ``bars`` where the entry
    would have taken place under ``scenario``. ``bars`` must include
    a ``timestamp`` column and an ET-anchored time-of-day index."""
    if bars.empty:
        return None
    et = bars["timestamp"].dt.tz_convert("America/New_York") if (
        bars["timestamp"].dt.tz is not None
    ) else bars["timestamp"].dt.tz_localize("UTC").dt.tz_convert(
        "America/New_York",
    )

    if scenario == "session_open_actual":
        # First row of the session = the actual decision time.
        return 0
    if scenario.startswith("t_"):
        target = scenario[2:].replace("_", ":")
        h, m = (int(x) for x in target.split(":"))
        match = et[(et.dt.hour == h) & (et.dt.minute == m)]
        if not match.empty:
            return int(match.index[0])
        return None
    if scenario == "or_breakout_15m":
        # First bar after 09:45 ET whose high > opening-range high.
        first_15 = bars[(et.dt.hour == 9) & (et.dt.minute < 45)]
        if first_15.empty:
            return None
        or_high = float(first_15["high"].max())
        rest = bars[bars.index > first_15.index[-1]]
        breakout = rest[rest["high"] > or_high]
        if not breakout.empty:
            return int(breakout.index[0])
        return None
    if scenario == "vwap_reclaim_first":
        if "vwap" not in bars.columns:
            return None
        mask = bars["close"] >= bars["vwap"]
        if mask.any():
            return int(bars.index[mask][0])
        return None
    if scenario == "vwap_pullback_after_breakout":
        # First touchback to VWAP after the close has been > VWAP.
        if "vwap" not in bars.columns:
            return None
        above = bars["close"] > bars["vwap"]
        if not above.any():
            return None
        first_above = bars.index[above][0]
        tail = bars.loc[first_above + 1:]
        touch = tail[tail["low"] <= tail["vwap"]]
        if not touch.empty:
            return int(touch.index[0])
        return None
    if scenario == "first_close_above_prior_close":
        if "prior_close" not in bars.columns:
            return None
        mask = bars["close"] > bars["prior_close"]
        if mask.any():
            return int(bars.index[mask][0])
        return None
    return None


def _replay_exit_surface(
    bars: pd.DataFrame, entry_index: int, entry_price: float,
    surface: tuple[str, float, float, str | None],
) -> dict[str, Any]:
    """Phase 7.3 — walk ``bars`` from the entry forward, simulating
    a long with the given stop_pct/target_pct (and optional stop-
    management rule). Returns a dict of outcomes."""
    name, stop_pct, target_pct, rule = surface
    if entry_price <= 0:
        return {
            "exit_surface": name, "first_touch": None,
            "pnl_pct": 0.0, "exited_at": None,
        }
    stop_price = entry_price * (1.0 - stop_pct)
    target_price = entry_price * (1.0 + target_pct)
    peak = entry_price
    trough = entry_price
    tail = bars.iloc[entry_index:]
    for _, row in tail.iterrows():
        h = float(row.get("high") or entry_price)
        l = float(row.get("low") or entry_price)
        peak = max(peak, h)
        trough = min(trough, l)
        # Apply stop management.
        if rule == "breakeven_after_5_mfe":
            if peak / entry_price - 1.0 >= 0.05:
                stop_price = max(stop_price, entry_price)
        elif rule == "lock_3_after_8_mfe":
            if peak / entry_price - 1.0 >= 0.08:
                stop_price = max(stop_price, entry_price * 1.03)
        if l <= stop_price:
            pnl = (stop_price - entry_price) / entry_price
            return {
                "exit_surface": name,
                "first_touch": "stop",
                "pnl_pct": pnl,
                "exited_at": str(row.get("timestamp")),
                "mfe_pct": (peak - entry_price) / entry_price,
                "mae_pct": (trough - entry_price) / entry_price,
            }
        if h >= target_price:
            pnl = target_pct
            return {
                "exit_surface": name,
                "first_touch": "target",
                "pnl_pct": pnl,
                "exited_at": str(row.get("timestamp")),
                "mfe_pct": (peak - entry_price) / entry_price,
                "mae_pct": (trough - entry_price) / entry_price,
            }
    # Time out at end of bars.
    final_close = float(tail.iloc[-1].get("close") or entry_price)
    pnl = (final_close - entry_price) / entry_price
    return {
        "exit_surface": name,
        "first_touch": "time_out",
        "pnl_pct": pnl,
        "exited_at": str(tail.iloc[-1].get("timestamp")),
        "mfe_pct": (peak - entry_price) / entry_price,
        "mae_pct": (trough - entry_price) / entry_price,
    }


def _path_metrics(bars: pd.DataFrame, entry_index: int,
                   entry_price: float) -> dict[str, float | None]:
    if bars.empty or entry_price <= 0:
        return {"mfe_pct": 0.0, "mae_pct": 0.0,
                "time_to_mfe_seconds": None}
    tail = bars.iloc[entry_index:]
    if tail.empty:
        return {"mfe_pct": 0.0, "mae_pct": 0.0,
                "time_to_mfe_seconds": None}
    peak = float(tail["high"].max()) if "high" in tail.columns else entry_price
    trough = float(tail["low"].min()) if "low" in tail.columns else entry_price
    out = {
        "mfe_pct": (peak - entry_price) / entry_price,
        "mae_pct": (trough - entry_price) / entry_price,
    }
    if "high" in tail.columns:
        peak_idx = tail["high"].idxmax()
        entry_ts = _to_minute_dt(tail.iloc[0].get("timestamp"))
        peak_ts = _to_minute_dt(tail.loc[peak_idx].get("timestamp"))
        if entry_ts and peak_ts:
            out["time_to_mfe_seconds"] = (peak_ts - entry_ts).total_seconds()
        else:
            out["time_to_mfe_seconds"] = None
    else:
        out["time_to_mfe_seconds"] = None
    return out


def compute_counterfactuals(
    candidate: dict, bars: pd.DataFrame, cfg: dict,
) -> list[dict]:
    """Returns one record per entry_scenario. Each record has the
    schema from report §7.7 (entry_scenario, exit_surface,
    path_metrics)."""
    if bars.empty:
        return []
    if "timestamp" not in bars.columns:
        bars = bars.reset_index().rename(
            columns={bars.index.name or "index": "timestamp"},
        )
    bars["timestamp"] = pd.to_datetime(bars["timestamp"])
    out: list[dict] = []
    for scenario in ENTRY_SCENARIOS:
        idx = _pick_entry_index(scenario, bars)
        record = {
            "session_date": candidate.get("session_date"),
            "symbol": candidate.get("ticker") or candidate.get("symbol"),
            "entry_scenario": scenario,
            "entry_index": idx,
        }
        if idx is None:
            record["entry_price"] = None
            record["path_metrics"] = None
            record["surfaces"] = []
            out.append(record)
            continue
        # Use the open of the entry minute as the fill proxy.
        entry_price = float(bars.iloc[idx].get("open") or bars.iloc[idx].get("close") or 0)
        record["entry_price"] = entry_price
        record["path_metrics"] = _path_metrics(bars, idx, entry_price)
        record["surfaces"] = [
            _replay_exit_surface(bars, idx, entry_price, s)
            for s in EXIT_SURFACES
        ]
        out.append(record)
    return out


def write_counterfactual_records(
    records: Iterable[dict], cfg: dict, session_date: str,
) -> Path:
    """Append the records to ``data/<env>/counterfactuals/<date>.jsonl``.
    Returns the path written."""
    base = bw._ledger_base_dir(cfg)
    env = bw._strategy_environment(cfg)
    out_dir = base / env / "counterfactuals"
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / f"{session_date}.jsonl"
    with open(out_path, "a", encoding="utf-8") as f:
        for rec in records:
            f.write(json.dumps(rec, default=str) + "\n")
    return out_path


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Bowaka counterfactual entry & exit replay",
    )
    parser.add_argument("--date", required=True,
                        help="Session date (YYYY-MM-DD)")
    parser.add_argument("--env", default="paper",
                        help="Environment (paper|test|live)")
    parser.add_argument("--config",
                        default=str(_SCRIPT_DIR / "bowaka_strategy.yaml"),
                        help="Path to strategy YAML")
    args = parser.parse_args(argv)

    cfg = bw.load_config(args.config)
    cfg.setdefault("strategy", {})["environment"] = args.env
    base = bw._ledger_base_dir(cfg)
    bars_dir = base / args.env / "candidate_bars"
    if not bars_dir.exists():
        print(f"no candidate-bar dir at {bars_dir}", file=sys.stderr)
        return 2
    bars_path = bars_dir / f"bars_{args.date}.parquet"
    if not bars_path.exists():
        # Try jsonl fallback.
        bars_path_jsonl = bars_dir / f"bars_{args.date}.jsonl.gz"
        if bars_path_jsonl.exists():
            df = pd.read_json(bars_path_jsonl, lines=True, compression="gzip")
        else:
            print(f"no bars file for {args.date}", file=sys.stderr)
            return 3
    else:
        df = pd.read_parquet(bars_path)
    if df.empty:
        print(f"empty bars for {args.date}", file=sys.stderr)
        return 4
    # Group by symbol.
    if "symbol" not in df.columns:
        print("expected 'symbol' column in bars", file=sys.stderr)
        return 5
    total = 0
    for sym, group in df.groupby("symbol"):
        candidate = {"ticker": sym, "session_date": args.date}
        recs = compute_counterfactuals(candidate, group.reset_index(drop=True), cfg)
        write_counterfactual_records(recs, cfg, args.date)
        total += len(recs)
    print(f"wrote {total} counterfactual records to {args.date}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
