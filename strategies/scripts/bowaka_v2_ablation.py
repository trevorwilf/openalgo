#!/usr/bin/env python3
"""Bowaka v2 — ablation harness.

Reads a base config and runs the backtester with one gate removed
or one timing tweak applied. Emits a comparable per-run summary
JSON for cross-ablation bucket analysis (handoff §8.5).
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

import yaml  # noqa: E402

import bowaka_v2_backtest as backtest  # noqa: E402


LOG = logging.getLogger("bowaka_v2_ablation")


# The complete set of ablations per handoff §8.5.
ALL_ABLATIONS: tuple[str, ...] = (
    "none",
    "remove_volume_gate",
    "remove_range_expansion",
    "remove_close_location",
    "remove_ema_slope",
    "remove_ema_distance",
    "remove_gap_cap",
    "remove_adv_cap",
    "randomize_entry",
    "shuffle_timestamps",
    "delay_entry_1m",
    "delay_entry_5m",
    "delay_entry_15m",
    "delay_entry_30m",
)


def run_ablation_suite(
    *,
    cfg: dict,
    sessions: list[str],
    symbols: list[str],
    minute_bars_supplier,
    daily_bars_supplier,
    ablations: Iterable[str] = ALL_ABLATIONS,
    cost_stress: str = "base",
    output_dir: Path,
) -> dict[str, dict]:
    """Run the backtester for each ablation; emit a comparable
    summary per run. Returns a dict ``{ablation: summary_dict}``."""
    output_dir.mkdir(parents=True, exist_ok=True)
    out: dict[str, dict] = {}
    for ab in ablations:
        LOG.info("running ablation: %s", ab)
        trades, summary = backtest.run_backtest(
            cfg=cfg, sessions=sessions, symbols=symbols,
            minute_bars_supplier=minute_bars_supplier,
            daily_bars_supplier=daily_bars_supplier,
            cost_stress=cost_stress,
            ablation=ab,
        )
        run_dir = output_dir / ab
        backtest.write_outputs(trades, summary, run_dir)
        out[ab] = {
            "trade_count": summary.trade_count,
            "win_rate": summary.win_rate,
            "mean_pnl_pct": summary.mean_pnl_pct,
            "total_pnl": summary.total_pnl,
            "exits_by_reason": summary.exits_by_reason,
        }
    (output_dir / "ablation_summary.json").write_text(
        json.dumps(out, indent=2)
    )
    return out


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Bowaka v2 ablation harness")
    parser.add_argument("--config", required=True)
    parser.add_argument("--from", dest="date_from", required=True)
    parser.add_argument("--to", dest="date_to", required=True)
    parser.add_argument("--symbols", required=True)
    parser.add_argument("--output-dir", required=True)
    parser.add_argument(
        "--ablation", action="append", default=None,
        help="Add a single ablation to run (repeatable). Default = all.",
    )
    parser.add_argument("--cost-stress", default="base")
    parser.add_argument("--synth", action="store_true")
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO,
                          format="%(asctime)s %(name)s %(levelname)s %(message)s")
    cfg = yaml.safe_load(Path(args.config).read_text(encoding="utf-8"))
    import pandas as pd
    sessions = pd.date_range(
        args.date_from, args.date_to, freq="B",
    ).strftime("%Y-%m-%d").tolist()
    symbols_file = Path(args.symbols)
    if symbols_file.exists():
        symbols = [
            s.strip() for s in symbols_file.read_text().splitlines() if s.strip()
        ]
    else:
        symbols = ["AAA", "BBB"]
    ablations = args.ablation or ALL_ABLATIONS
    run_ablation_suite(
        cfg=cfg, sessions=sessions, symbols=symbols,
        minute_bars_supplier=backtest._synth_minute_bars,
        daily_bars_supplier=backtest._synth_daily_bars,
        ablations=ablations,
        cost_stress=args.cost_stress,
        output_dir=Path(args.output_dir),
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
