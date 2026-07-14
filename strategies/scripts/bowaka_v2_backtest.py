#!/usr/bin/env python3
"""Bowaka v2 — intraday replay backtester.

Algorithm per handoff §7.2.1: replay minute bars sequentially,
expose only data available at each scan time. CRITICALLY uses the
SAME feature functions as the live scanner (bowaka_v2_features),
so feature-parity drift between scanner and backtester is
structurally impossible.

CLI:
  python bowaka_v2_backtest.py \\
    --config bowaka_v2_config.yaml \\
    --from 2026-05-15 --to 2026-05-15 \\
    --symbols tests/fixtures/symbols_small.txt \\
    --output-dir /tmp/backtest_out \\
    --cost-stress conservative \\
    --ablation none
"""
from __future__ import annotations

import argparse
import json
import logging
import sys
from dataclasses import dataclass, field
from datetime import datetime, time, timedelta, timezone
from pathlib import Path
from typing import Any, Callable, Iterable

_SCRIPT_DIR = Path(__file__).resolve().parent
if str(_SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPT_DIR))

import pandas as pd  # noqa: E402
import yaml  # noqa: E402

import bowaka_v2_features as features  # noqa: E402
import bowaka_v2_paths as paths  # noqa: E402
import bowaka_v2_cost_model as costs  # noqa: E402


LOG = logging.getLogger("bowaka_v2_backtest")


@dataclass
class BacktestTrade:
    session_date: str
    symbol: str
    entry_ts: str
    entry_price: float
    qty: int
    notional: float
    stop_price: float
    target_price: float
    max_hold_session_minutes: int
    exit_ts: str | None = None
    exit_price: float | None = None
    exit_reason: str | None = None
    pnl_dollars: float | None = None
    pnl_pct: float | None = None
    adv_at_entry: float | None = None
    spread_bps_at_entry: float | None = None


@dataclass
class BacktestSummary:
    trade_count: int = 0
    win_count: int = 0
    win_rate: float = 0.0
    mean_pnl_pct: float = 0.0
    median_pnl_pct: float = 0.0
    total_pnl: float = 0.0
    exits_by_reason: dict[str, int] = field(default_factory=dict)


def run_backtest(
    *,
    cfg: dict,
    sessions: list[str],
    symbols: list[str],
    minute_bars_supplier: Callable[[str, str], pd.DataFrame],
    daily_bars_supplier: Callable[[str, str], pd.DataFrame],
    quote_supplier: Callable[[str, str, datetime], dict] | None = None,
    cost_stress: str = "base",
    ablation: str = "none",
) -> tuple[list[BacktestTrade], BacktestSummary]:
    """Run a multi-session backtest.

    ``minute_bars_supplier(symbol, session_date)`` returns the full
    session's minute-bar DataFrame (regular hours).
    ``daily_bars_supplier(symbol, session_date)`` returns prior
    daily bars (ending the day before).
    ``quote_supplier(symbol, session_date, scan_ts)`` returns a
    {bid, ask} dict, or None to use the bar's close as both.
    """
    trades: list[BacktestTrade] = []
    sig_cfg = _apply_ablation(cfg.get("signals", {}) or {}, ablation)
    sizing_cfg = cfg.get("sizing", {}) or {}
    exits_cfg = cfg.get("exits", {}) or {}
    score_cfg = cfg.get("score", {}) or {}
    scanner_cfg = cfg.get("scanner", {}) or {}
    risk_cfg = cfg.get("risk", {}) or {}

    bankroll = float(sizing_cfg.get("bankroll_fixed_dollars", 90000))
    n_slots = int(sizing_cfg.get("max_concurrent_positions", 18))
    slice_frac = float(sizing_cfg.get("equal_slice_bankroll_fraction", 0.80))
    per_trade = bankroll * slice_frac / n_slots
    stop_pct = float(exits_cfg.get("stop_pct", 0.08))
    target_pct = float(exits_cfg.get("target_pct", 0.15))
    max_hold_days = int(exits_cfg.get("max_hold_days", 3))
    scan_interval = int(scanner_cfg.get("scan_interval_seconds", 60))
    max_daily_entries = int(risk_cfg.get("max_total_entries_per_day", 10))

    for session_date in sessions:
        entered_today: set[str] = set()
        daily_entry_count = 0
        # Precompute baselines + bars for each symbol this session.
        per_symbol: dict[str, dict] = {}
        for sym in symbols:
            daily = daily_bars_supplier(sym, session_date)
            if daily is None or len(daily) == 0:
                continue
            baselines = features.compute_prior_daily_baselines(daily)
            minutes = minute_bars_supplier(sym, session_date)
            if minutes is None or len(minutes) == 0:
                continue
            per_symbol[sym] = {
                "baselines": baselines, "minutes": minutes,
            }

        if not per_symbol:
            continue

        # Iterate scan times across the session.
        scan_times = _session_scan_times(session_date, scan_interval)
        delay = _ablation_delay_minutes(ablation)
        for scan_t in scan_times:
            if daily_entry_count >= max_daily_entries:
                break
            candidates: list[tuple[float, str, dict, dict]] = []
            for sym, ctx in per_symbol.items():
                if sym in entered_today:
                    continue
                through_t = ctx["minutes"][
                    ctx["minutes"]["timestamp"] <= scan_t
                ]
                if len(through_t) == 0:
                    continue
                sess = features.aggregate_forming_session_bar(through_t)
                vcf = features.compute_volume_curve_fraction(
                    None, scan_t, "default",
                )
                feats = features.compute_forming_session_features(
                    sess, ctx["baselines"], vcf,
                )
                ok, gates = features.apply_v2_gates(
                    feats, sig_cfg,
                    price=sess.get("last_price"),
                    avg_dollar_volume_20d=ctx["baselines"].get(
                        "avg_dollar_volume_20d",
                    ),
                    prior_atr_pct=ctx["baselines"].get("prior_atr_pct"),
                    ema_slope_prior=ctx["baselines"].get("ema_slope_prior"),
                    instrument_class="operating_equity",
                )
                if not ok:
                    continue
                score = features.compute_signal_strength(
                    feats, score_cfg,
                    ema_slope_prior=ctx["baselines"].get("ema_slope_prior"),
                )
                candidates.append((score, sym, sess, feats))

            candidates.sort(key=lambda x: -x[0])
            for _score, sym, sess, feats in candidates[:1]:
                # Entry occurs `delay` minutes later (ablation).
                effective_entry = scan_t + timedelta(minutes=delay)
                bars = per_symbol[sym]["minutes"]
                entry_bar = bars[bars["timestamp"] >= effective_entry]
                if len(entry_bar) == 0:
                    continue
                entry_row = entry_bar.iloc[0]
                entry_quote_bid = float(entry_row.get("low") or entry_row["close"])
                entry_quote_ask = float(entry_row.get("high") or entry_row["close"])
                if quote_supplier:
                    q = quote_supplier(sym, session_date, effective_entry)
                    if q:
                        entry_quote_bid = float(q.get("bid", entry_quote_bid))
                        entry_quote_ask = float(q.get("ask", entry_quote_ask))
                last_price = float(entry_row["close"])
                qty = int(per_trade // last_price)
                if qty <= 0:
                    continue
                fill = costs.estimate_entry_fill(
                    quote_bid=entry_quote_bid,
                    quote_ask=entry_quote_ask,
                    notional=qty * last_price,
                    avg_dollar_volume=per_symbol[sym]["baselines"].get(
                        "avg_dollar_volume_20d",
                    ),
                    stress=cost_stress,
                )
                stop_price = fill.fill_price * (1 - stop_pct)
                target_price = fill.fill_price * (1 + target_pct)

                # Manage position forward through bars.
                manage_bars = bars[bars["timestamp"] >= effective_entry]
                trade = BacktestTrade(
                    session_date=session_date, symbol=sym,
                    entry_ts=str(entry_row["timestamp"]),
                    entry_price=fill.fill_price, qty=qty,
                    notional=qty * fill.fill_price,
                    stop_price=stop_price, target_price=target_price,
                    max_hold_session_minutes=int(max_hold_days * 390),
                    adv_at_entry=per_symbol[sym]["baselines"].get(
                        "avg_dollar_volume_20d",
                    ),
                    spread_bps_at_entry=(
                        (entry_quote_ask - entry_quote_bid)
                        / max(last_price, 1e-9) * 10_000.0
                    ),
                )
                _manage_position(
                    trade, manage_bars,
                    stop_price=stop_price, target_price=target_price,
                    cost_stress=cost_stress,
                    adv=per_symbol[sym]["baselines"].get(
                        "avg_dollar_volume_20d",
                    ),
                )
                trades.append(trade)
                entered_today.add(sym)
                daily_entry_count += 1
                if daily_entry_count >= max_daily_entries:
                    break

    return trades, _build_summary(trades)


def _session_scan_times(
    session_date: str, interval_seconds: int,
) -> list[datetime]:
    """Generate scan times every interval_seconds between 09:45 ET
    and 15:30 ET on session_date."""
    base = pd.Timestamp(session_date + " 09:45", tz="America/New_York")
    end = pd.Timestamp(session_date + " 15:30", tz="America/New_York")
    out: list[datetime] = []
    t = base
    step = pd.Timedelta(seconds=interval_seconds)
    while t <= end:
        out.append(t.to_pydatetime())
        t = t + step
    return out


def _ablation_delay_minutes(ablation: str) -> int:
    if ablation == "delay_entry_1m":  return 1
    if ablation == "delay_entry_5m":  return 5
    if ablation == "delay_entry_15m": return 15
    if ablation == "delay_entry_30m": return 30
    return 0


def _apply_ablation(signals_cfg: dict, ablation: str) -> dict:
    """Strip a specific gate's threshold from signals_cfg per the
    ablation spec (handoff §8.5)."""
    if ablation == "none":
        return signals_cfg
    cfg = dict(signals_cfg)
    if ablation == "remove_volume_gate":
        cfg["rvol_so_far_min"] = None
        cfg["projected_full_day_rvol_min"] = None
    elif ablation == "remove_range_expansion":
        cfg["range_expansion_so_far_min"] = None
    elif ablation == "remove_close_location":
        cfg["close_location_so_far_min"] = None
    elif ablation == "remove_ema_slope":
        cfg["ema_slope_min"] = None
    elif ablation == "remove_ema_distance":
        cfg["ema_distance_min"] = None
    elif ablation == "remove_gap_cap":
        cfg["gap_pct_max"] = None
    elif ablation == "remove_adv_cap":
        cfg["avg_dollar_volume_min"] = None
        cfg["avg_dollar_volume_max"] = None
    # delay_entry_* don't change signals_cfg; the backtester reads
    # _ablation_delay_minutes.
    return cfg


def _manage_position(
    trade: BacktestTrade, bars: pd.DataFrame, *,
    stop_price: float, target_price: float,
    cost_stress: str, adv: float | None,
) -> None:
    """Walk the bar series after entry. Exit on first touch of
    stop, target, or end of bars (time_stop)."""
    for _, bar in bars.iterrows():
        low = float(bar.get("low") or bar["close"])
        high = float(bar.get("high") or bar["close"])
        if low <= stop_price:
            exit_fill = costs.estimate_exit_fill(
                quote_bid=stop_price * 0.999, quote_ask=stop_price * 1.001,
                notional=trade.notional, avg_dollar_volume=adv,
                stress=cost_stress,
            )
            trade.exit_ts = str(bar["timestamp"])
            trade.exit_price = exit_fill.fill_price
            trade.exit_reason = "stop_hit"
            break
        if high >= target_price:
            exit_fill = costs.estimate_exit_fill(
                quote_bid=target_price * 0.999, quote_ask=target_price * 1.001,
                notional=trade.notional, avg_dollar_volume=adv,
                stress=cost_stress,
            )
            trade.exit_ts = str(bar["timestamp"])
            trade.exit_price = exit_fill.fill_price
            trade.exit_reason = "target_hit"
            break
    else:
        # No exit triggered — time_stop at last bar.
        last = bars.iloc[-1]
        exit_fill = costs.estimate_exit_fill(
            quote_bid=float(last["close"]) * 0.999,
            quote_ask=float(last["close"]) * 1.001,
            notional=trade.notional, avg_dollar_volume=adv,
            stress=cost_stress,
        )
        trade.exit_ts = str(last["timestamp"])
        trade.exit_price = exit_fill.fill_price
        trade.exit_reason = "time_stop"

    trade.pnl_dollars = (
        (trade.exit_price - trade.entry_price) * trade.qty
    )
    trade.pnl_pct = (
        (trade.exit_price - trade.entry_price) / trade.entry_price
    )


def _build_summary(trades: list[BacktestTrade]) -> BacktestSummary:
    if not trades:
        return BacktestSummary()
    pnls = [t.pnl_pct for t in trades if t.pnl_pct is not None]
    wins = [p for p in pnls if p > 0]
    reasons: dict[str, int] = {}
    for t in trades:
        reasons[t.exit_reason or "?"] = reasons.get(t.exit_reason or "?", 0) + 1
    return BacktestSummary(
        trade_count=len(trades),
        win_count=len(wins),
        win_rate=len(wins) / len(trades),
        mean_pnl_pct=sum(pnls) / len(pnls) if pnls else 0.0,
        median_pnl_pct=sorted(pnls)[len(pnls) // 2] if pnls else 0.0,
        total_pnl=sum((t.pnl_dollars or 0.0) for t in trades),
        exits_by_reason=reasons,
    )


def write_outputs(
    trades: list[BacktestTrade], summary: BacktestSummary,
    out_dir: Path,
) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    df = pd.DataFrame([t.__dict__ for t in trades])
    df.to_parquet(out_dir / "trades.parquet", index=False)
    (out_dir / "summary.json").write_text(
        json.dumps({
            "trade_count": summary.trade_count,
            "win_count": summary.win_count,
            "win_rate": summary.win_rate,
            "mean_pnl_pct": summary.mean_pnl_pct,
            "median_pnl_pct": summary.median_pnl_pct,
            "total_pnl": summary.total_pnl,
            "exits_by_reason": summary.exits_by_reason,
        }, indent=2)
    )


# ---------------------------------------------------------------- CLI


def _synth_minute_bars(symbol: str, session_date: str) -> pd.DataFrame:
    """Synthetic bars for the smoke runs."""
    base = pd.Timestamp(session_date + " 09:30", tz="America/New_York")
    rows = []
    for i in range(390):
        ts = base + pd.Timedelta(minutes=i)
        close = 10.0 + 0.005 * i
        rows.append({
            "timestamp": ts.tz_convert("UTC"),
            "open": close, "high": close * 1.005,
            "low": close * 0.995, "close": close,
            "volume": 5000.0,
        })
    return pd.DataFrame(rows)


def _synth_daily_bars(symbol: str, session_date: str) -> pd.DataFrame:
    end = pd.Timestamp(session_date) - pd.Timedelta(days=1)
    rows = []
    for i in range(25):
        ts = end - pd.Timedelta(days=24 - i)
        rows.append({
            "timestamp": ts.tz_localize("UTC"),
            "open": 9.0 + i * 0.04, "high": 9.5 + i * 0.04,
            "low": 8.5 + i * 0.04, "close": 9.0 + i * 0.04,
            "volume": 500_000,
        })
    return pd.DataFrame(rows)


# ---- lake-backed suppliers (the DEFAULT when --synth is not passed) ----------
# A paired lab-vs-prod parity run pins both sides to the same lake and reads it
# through the SAME bowaka_common reader, so the two read identically.

def _resolve_backtest_lake_root(args: argparse.Namespace, cfg: dict) -> Path:
    """Resolve the market-data lake root for a lake-backed run.

    Precedence: ``--lake-root`` CLI > ``market_data.shared_root`` in the config >
    ``$MARKET_DATA_ROOT``. Raises if none resolve (the caller wants lake data but
    gave no root — pass ``--lake-root`` / set the env, or use ``--synth``).
    """
    import os

    root = getattr(args, "lake_root", None)
    if not root:
        root = (cfg.get("market_data") or {}).get("shared_root")
    if not root:
        root = os.environ.get("MARKET_DATA_ROOT")
    if not root:
        raise ValueError(
            "no market-data lake root resolved -- pass --lake-root, set "
            "market_data.shared_root in the config, export $MARKET_DATA_ROOT, "
            "or run with --synth for the synthetic smoke suppliers."
        )
    return Path(root)


def _resolve_required_adjustment(cfg: dict) -> str:
    """The daily-bar adjustment the config requires.

    ``'split_adjusted'`` when the config sets ``require_split_adjustment`` or
    ``require_adjusted_daily_bars`` (an intended-realism contract), else
    ``'raw'``. Mirrors the lab's ``daily_adjustment_for_config`` so the prior-day
    baselines (ATR%, EMA, ADV) are computed off the same adjustment on both sides.
    """
    md = cfg.get("market_data") or {}
    if md.get("require_split_adjustment") or md.get("require_adjusted_daily_bars"):
        return "split_adjusted"
    return "raw"


def _make_lake_suppliers(
    lake_root: Path, cfg: dict, adjustment: str,
) -> tuple[
    Callable[[str, str], pd.DataFrame],
    Callable[[str, str], pd.DataFrame],
    Callable[[str, str, datetime], dict] | None,
]:
    """Build ``(minute_bars_supplier, daily_bars_supplier, quote_supplier)``
    reading the shared lake via ``bowaka_common.marketdata.MarketDataStore`` — the
    SAME reader the lab uses, so a paired run reads identically.

    ``minute_bars_supplier(symbol, session_date)`` → the session's minute bars
    (the caller filters by scan time). ``daily_bars_supplier(symbol, session_date)``
    → the trailing daily bars ending the day BEFORE the session (no look-ahead).
    """
    from bowaka_common.marketdata import MarketDataStore

    md = cfg.get("market_data") or {}
    feed = str(md.get("feed", "iex"))
    vendor = str(md.get("vendor", "alpaca"))
    daily_lookback_days = 400
    store = MarketDataStore(lake_root, vendor=vendor)

    def minute_bars_supplier(symbol: str, session_date: str) -> pd.DataFrame:
        start = pd.Timestamp(session_date + " 00:00", tz="America/New_York").tz_convert("UTC")
        end = pd.Timestamp(session_date + " 23:59", tz="America/New_York").tz_convert("UTC")
        return store.minute_bars(symbol, start, end, feed=feed)

    def daily_bars_supplier(symbol: str, session_date: str) -> pd.DataFrame:
        end = pd.Timestamp(session_date).date() - timedelta(days=1)
        start = end - timedelta(days=daily_lookback_days)
        return store.daily_bars(symbol, start, end, feed=feed, adjustment=adjustment)

    # The prod backtester's quote handling falls back to the bar low/high when no
    # quote_supplier is wired (entry bid/ask). Lake quotes are not wired here.
    return minute_bars_supplier, daily_bars_supplier, None


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Bowaka v2 backtester")
    parser.add_argument("--config", required=True)
    parser.add_argument("--from", dest="date_from", required=True)
    parser.add_argument("--to", dest="date_to", required=True)
    parser.add_argument("--symbols", required=True,
                        help="Path to a text file with one symbol per line.")
    parser.add_argument("--output-dir", required=True)
    parser.add_argument("--cost-stress", default="base",
                        choices=["base", "conservative", "severe"])
    parser.add_argument("--ablation", default="none")
    parser.add_argument(
        "--synth", action="store_true",
        help="Use built-in synthetic bar suppliers (smoke).",
    )
    parser.add_argument(
        "--lake-root", dest="lake_root", default=None,
        help="Market-data lake root for the default (lake-backed) suppliers. "
             "Falls back to market_data.shared_root / $MARKET_DATA_ROOT.",
    )
    args = parser.parse_args(argv)

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(name)s %(levelname)s %(message)s",
    )
    cfg = yaml.safe_load(Path(args.config).read_text(encoding="utf-8"))
    symbols_file = Path(args.symbols)
    if symbols_file.exists():
        symbols = [
            s.strip() for s in symbols_file.read_text().splitlines()
            if s.strip()
        ]
    else:
        symbols = ["AAA", "BBB"]
    sessions = pd.date_range(
        args.date_from, args.date_to, freq="B",
    ).strftime("%Y-%m-%d").tolist()

    if not args.synth and not symbols_file.exists():
        LOG.error("symbols file %s not found and --synth not set", symbols_file)
        return 2

    # Default to LAKE-backed suppliers; --synth selects the synthetic smoke
    # suppliers. (The pre-fix code had a dead ternary that returned the synthetic
    # suppliers on BOTH branches, so every run silently used synthetic data.)
    if args.synth:
        minute_bars = _synth_minute_bars
        daily_bars = _synth_daily_bars
        quote_supplier = None
    else:
        lake_root = _resolve_backtest_lake_root(args, cfg)
        adjustment = _resolve_required_adjustment(cfg)
        LOG.info("lake-backed suppliers: root=%s adjustment=%s", lake_root, adjustment)
        minute_bars, daily_bars, quote_supplier = _make_lake_suppliers(
            lake_root, cfg, adjustment,
        )

    trades, summary = run_backtest(
        cfg=cfg, sessions=sessions, symbols=symbols,
        minute_bars_supplier=minute_bars,
        daily_bars_supplier=daily_bars,
        quote_supplier=quote_supplier,
        cost_stress=args.cost_stress,
        ablation=args.ablation,
    )
    write_outputs(trades, summary, Path(args.output_dir))
    LOG.info(
        "backtest done: trades=%d, total_pnl=%.2f, win_rate=%.3f",
        summary.trade_count, summary.total_pnl, summary.win_rate,
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
