#!/usr/bin/env python3
"""Bowaka v2 — time-of-day volume curve builder.

Computes the expected cumulative full-day volume fraction by
minute-of-day for each ADV bucket. The intraday scanner uses this
curve to convert "session volume so far" into a participation
ratio (RVOL-so-far / projected_full_day_rvol).

Causal contract: the curve is built from PRIOR sessions only. The
current session must NOT contribute to the curve it consumes —
that would let today's volume bias today's RVOL.

The bucket assignment uses ``cfg.historical_features.volume_curve.
bucket_edges`` from bowaka_v2_config.yaml.

CLI:
  python bowaka_v2_volume_curve.py --config <yaml> --minute-bars-dir <dir>
  python bowaka_v2_volume_curve.py --config <yaml> --synthesize  # demo
"""
from __future__ import annotations

import argparse
import logging
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable

_SCRIPT_DIR = Path(__file__).resolve().parent
if str(_SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPT_DIR))

import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402
import yaml  # noqa: E402

import bowaka_v2_paths as paths  # noqa: E402


LOG = logging.getLogger("bowaka_v2_volume_curve")


def adv_bucket(adv_dollars: float | None, bucket_edges: list[float]) -> str:
    """Bucket label for a symbol given its 20d avg dollar volume.

    bucket_edges follows §6 default [250000, 500000, 1000000,
    5000000, 20000000]. Labels: '<250k', '250k_500k', '500k_1M',
    '1M_5M', '5M_20M', '20M+'. None or below-min → '<250k'.
    """
    if adv_dollars is None or adv_dollars < bucket_edges[0]:
        return f"<{_pretty(bucket_edges[0])}"
    for i in range(len(bucket_edges) - 1):
        lo, hi = bucket_edges[i], bucket_edges[i + 1]
        if lo <= adv_dollars < hi:
            return f"{_pretty(lo)}_{_pretty(hi)}"
    return f"{_pretty(bucket_edges[-1])}+"


def _pretty(n: float) -> str:
    n = float(n)
    if n >= 1_000_000:
        return f"{int(n / 1_000_000)}M"
    if n >= 1_000:
        return f"{int(n / 1_000)}k"
    return f"{int(n)}"


def build_curve_from_minute_bars(
    minute_bars: pd.DataFrame,
    *,
    bucket_edges: list[float],
    adv_lookup: dict[str, float] | None = None,
) -> pd.DataFrame:
    """Build the curve from a frame of historical minute bars.

    Schema expected in ``minute_bars``:
    - timestamp (datetime, tz-aware)
    - symbol (str)
    - volume (float)
    - (optional) adv_bucket or adv_dollars; otherwise looked up
      via ``adv_lookup[symbol]``.

    Returns a DataFrame with columns:
    - minute_of_day (int 0-389)
    - adv_bucket (str)
    - cumulative_fraction (float)
    """
    if minute_bars is None or len(minute_bars) == 0:
        return pd.DataFrame(columns=[
            "minute_of_day", "adv_bucket", "cumulative_fraction",
        ])

    df = minute_bars.copy()
    cols = {c.lower(): c for c in df.columns}
    ts_col = cols.get("timestamp") or cols.get("ts")
    sym_col = cols.get("symbol")
    vol_col = cols.get("volume")
    if not (ts_col and sym_col and vol_col):
        raise ValueError("expected timestamp, symbol, volume columns")

    # ET minute-of-day.
    df["timestamp"] = pd.to_datetime(df[ts_col])
    if df["timestamp"].dt.tz is None:
        df["timestamp"] = df["timestamp"].dt.tz_localize("UTC")
    et = df["timestamp"].dt.tz_convert("America/New_York")
    df["minute_of_day"] = (
        (et.dt.hour - 9) * 60 + (et.dt.minute - 30)
    ).clip(lower=0, upper=389)

    # Bucket assignment.
    if "adv_bucket" not in cols:
        adv_lookup = adv_lookup or {}
        df["adv_bucket"] = df[sym_col].map(
            lambda s: adv_bucket(adv_lookup.get(s), bucket_edges)
        )
    else:
        df["adv_bucket"] = df[cols["adv_bucket"]]
    df["session_date"] = et.dt.date
    df["volume"] = pd.to_numeric(df[vol_col], errors="coerce").fillna(0.0)

    # Step 1: per-session total volume per (symbol, session_date).
    per_session_total = df.groupby(
        ["adv_bucket", "session_date", sym_col]
    )["volume"].sum().rename("session_total")

    # Step 2: cumulative volume per (symbol, session_date) by minute.
    df = df.sort_values([sym_col, "session_date", "minute_of_day"])
    df["cum_volume"] = df.groupby(
        ["adv_bucket", "session_date", sym_col]
    )["volume"].cumsum()
    df = df.merge(
        per_session_total.reset_index(),
        on=["adv_bucket", "session_date", sym_col],
    )
    df["fraction"] = df.apply(
        lambda r: r["cum_volume"] / r["session_total"]
        if r["session_total"] > 0 else 0.0,
        axis=1,
    )

    # Step 3: average fraction by (adv_bucket, minute_of_day).
    out = df.groupby(
        ["adv_bucket", "minute_of_day"]
    )["fraction"].mean().reset_index()
    out = out.rename(columns={"fraction": "cumulative_fraction"})
    return out.sort_values(["adv_bucket", "minute_of_day"]).reset_index(drop=True)


def synthesize_default_curve(bucket_edges: list[float]) -> pd.DataFrame:
    """Generate a reasonable default curve when historical bars are
    unavailable: ~8% in first 15 min, S-shaped accumulation with a
    bump near close. Identical curve across buckets — operators
    should rebuild from real bars once available."""
    rows = []
    buckets = (
        [f"<{_pretty(bucket_edges[0])}"]
        + [
            f"{_pretty(lo)}_{_pretty(hi)}"
            for lo, hi in zip(bucket_edges[:-1], bucket_edges[1:])
        ]
        + [f"{_pretty(bucket_edges[-1])}+"]
    )
    for b in buckets:
        for m in range(390):
            if m <= 15:
                frac = 0.08 * (m / 15.0)
            elif m <= 60:
                frac = 0.08 + 0.10 * ((m - 15) / 45.0)
            elif m <= 180:
                frac = 0.18 + 0.27 * ((m - 60) / 120.0)
            elif m <= 330:
                frac = 0.45 + 0.30 * ((m - 180) / 150.0)
            elif m <= 380:
                frac = 0.75 + 0.20 * ((m - 330) / 50.0)
            else:
                frac = 0.95 + 0.05 * ((m - 380) / 9.0)
            rows.append({
                "minute_of_day": m,
                "adv_bucket": b,
                "cumulative_fraction": min(max(frac, 0.0), 1.0),
            })
    return pd.DataFrame(rows)


def write_curve(curve_df: pd.DataFrame, out_path: Path) -> None:
    out_path.parent.mkdir(parents=True, exist_ok=True)
    tmp = out_path.with_suffix(out_path.suffix + ".tmp")
    try:
        curve_df.to_parquet(tmp, index=False)
    except Exception as e:
        LOG.warning("parquet write failed (%s); falling back to jsonl.gz", e)
        tmp = out_path.with_suffix(".jsonl.gz.tmp")
        out_path = out_path.with_suffix(".jsonl.gz")
        curve_df.to_json(tmp, orient="records", lines=True, compression="gzip")
    import os
    os.replace(tmp, out_path)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Bowaka v2 time-of-day volume curve builder",
    )
    parser.add_argument("--config", required=True)
    parser.add_argument("--minute-bars-dir", default=None,
                        help="Directory of historical minute-bar parquet "
                             "files (one per session date).")
    parser.add_argument("--synthesize", action="store_true",
                        help="Skip historical bars; write a synthesized "
                             "default curve. Useful for bootstrapping.")
    args = parser.parse_args(argv)

    cfg = yaml.safe_load(Path(args.config).read_text(encoding="utf-8"))
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(name)s %(levelname)s %(message)s",
    )

    hf = (cfg.get("historical_features") or {})
    vc = hf.get("volume_curve") or {}
    bucket_edges = list(vc.get("bucket_edges", [
        250000, 500000, 1000000, 5000000, 20000000,
    ]))

    if args.synthesize:
        LOG.info("synthesizing default curve")
        curve = synthesize_default_curve(bucket_edges)
    else:
        if not args.minute_bars_dir:
            LOG.error(
                "--minute-bars-dir required without --synthesize"
            )
            return 2
        bars_dir = Path(args.minute_bars_dir)
        files = sorted(bars_dir.glob("*.parquet"))
        if not files:
            LOG.error("no parquet files in %s", bars_dir)
            return 3
        frames = [pd.read_parquet(f) for f in files]
        bars = pd.concat(frames, ignore_index=True)
        curve = build_curve_from_minute_bars(
            bars, bucket_edges=bucket_edges,
        )

    out = _resolve(cfg.get("paths", {}).get("volume_curve_path"),
                    paths.VOLUME_CURVE_PATH)
    write_curve(curve, out)
    LOG.info("wrote curve to %s (%d rows)", out, len(curve))
    return 0


def _resolve(p: str | None, default: Path) -> Path:
    if not p:
        return default
    pp = Path(p)
    if pp.is_absolute():
        return pp
    return paths.REPO_ROOT / pp


if __name__ == "__main__":
    sys.exit(main())
