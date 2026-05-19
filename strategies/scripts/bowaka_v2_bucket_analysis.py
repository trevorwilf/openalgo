#!/usr/bin/env python3
"""Bowaka v2 — post-backtest bucket analysis.

Reads a backtest run's trades.parquet, assigns bucket labels per
handoff §8.6, and emits expectancy / Sharpe / hit-rate / max-DD per
bucket.
"""
from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path
from typing import Iterable

_SCRIPT_DIR = Path(__file__).resolve().parent
if str(_SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPT_DIR))

import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402


LOG = logging.getLogger("bowaka_v2_bucket_analysis")


def bucket_adv(adv: float | None) -> str:
    if adv is None or adv < 250_000: return "<250k"
    if adv < 500_000: return "250k_500k"
    if adv < 1_000_000: return "500k_1M"
    if adv < 5_000_000: return "1M_5M"
    if adv < 20_000_000: return "5M_20M"
    return "20M+"


def bucket_price(p: float | None) -> str:
    if p is None: return "?"
    if p < 2: return "$1_$2"
    if p < 5: return "$2_$5"
    if p < 10: return "$5_$10"
    return "$10_$20"


def bucket_spread_bps(s: float | None) -> str:
    if s is None: return "?"
    if s < 10: return "<10bps"
    if s < 25: return "10_25bps"
    if s < 50: return "25_50bps"
    if s < 100: return "50_100bps"
    return "100bps+"


def assign_buckets(trades_df: pd.DataFrame) -> pd.DataFrame:
    df = trades_df.copy()
    df["adv_bucket"] = df["adv_at_entry"].apply(bucket_adv)
    df["price_bucket"] = df["entry_price"].apply(bucket_price)
    df["spread_bucket"] = df["spread_bps_at_entry"].apply(bucket_spread_bps)
    return df


def bucket_stats(df: pd.DataFrame, bucket_col: str) -> pd.DataFrame:
    out = []
    for label, group in df.groupby(bucket_col):
        pnls = group["pnl_pct"].dropna()
        if len(pnls) == 0:
            continue
        out.append({
            "bucket": label, "n_trades": int(len(group)),
            "win_rate": float((pnls > 0).mean()),
            "mean_pnl_pct": float(pnls.mean()),
            "median_pnl_pct": float(pnls.median()),
            "std_pnl_pct": float(pnls.std() if len(pnls) > 1 else 0.0),
            "sharpe": float(
                pnls.mean() / pnls.std() * np.sqrt(252)
                if len(pnls) > 1 and pnls.std() > 0 else 0.0
            ),
            "max_dd_pct": float(pnls.min()),
        })
    return pd.DataFrame(out)


def analyze(trades_df: pd.DataFrame, out_dir: Path) -> dict:
    out_dir.mkdir(parents=True, exist_ok=True)
    df = assign_buckets(trades_df)
    results: dict[str, list[dict]] = {}
    for col in ("adv_bucket", "price_bucket", "spread_bucket"):
        stats = bucket_stats(df, col)
        stats.to_csv(out_dir / f"by_{col}.csv", index=False)
        results[col] = stats.to_dict("records")
    (out_dir / "bucket_summary.json").write_text(
        json.dumps(results, indent=2, default=str)
    )
    return results


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Bowaka v2 bucket analysis",
    )
    parser.add_argument("--trades", required=True,
                        help="Path to trades.parquet")
    parser.add_argument("--output-dir", required=True)
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO)
    df = pd.read_parquet(args.trades)
    res = analyze(df, Path(args.output_dir))
    LOG.info("bucket analysis: %d adv buckets, %d price buckets, %d spread buckets",
              len(res.get("adv_bucket", [])),
              len(res.get("price_bucket", [])),
              len(res.get("spread_bucket", [])))
    return 0


if __name__ == "__main__":
    sys.exit(main())
