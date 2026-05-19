"""Smoke tests for the bowaka_analysis toolkit.

Builds a synthetic per-trade jsonl with two trades — one target_hit
winner, one stop_hit loser — and asserts each loader / aggregator
produces sane shapes. Not a stats correctness battery; this is a
"the script imports, the loaders work, the aggregations run without
error" guard.
"""
from __future__ import annotations

import json
import sys
from datetime import datetime, timezone, timedelta
from pathlib import Path

import pandas as pd
import pytest


@pytest.fixture
def analysis_module():
    p = Path(__file__).resolve().parents[2] / "strategies" / "scripts"
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))
    import importlib
    return importlib.import_module("bowaka_analysis")


def _emit(path: Path, recs: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "a", encoding="utf-8") as f:
        for r in recs:
            f.write(json.dumps(r) + "\n")


def _trade_records(
    *, ticker: str, link_id: str, entry: float, exit_price: float,
    reason: str, slot: int, signal_strength: float = 9.0,
    rvol: float = 2.5, base_ts: datetime,
) -> list[dict]:
    """Synthesize a full lifecycle for one trade. Five intraday ticks
    walking from entry toward exit so the analysis script has data
    to compute drawdown_before_stop and runup_before_target."""
    qty = 100
    target = round(entry * 1.15, 2)
    stop = round(entry * 0.92, 2)

    decision = {
        "record_type": "entry_decision",
        "ts": base_ts.isoformat(),
        "ticker": ticker, "link_id": link_id,
        "venue_code": "XNAS", "exchange": "NASDAQ",
        "candidate": {
            "close": entry, "signal_strength": signal_strength,
            "features": {
                "rvol": rvol, "atr_pct": 0.08, "range_expansion": 1.4,
                "gap_pct": 0.02, "close_location": 0.85,
                "ema_distance": 0.05, "ema_slope": 0.02,
                "avg_dollar_volume": 1_000_000.0,
            },
        },
        "gates": {
            "rvol":           {"value": rvol, "threshold": 1.5, "passed": True},
            "atr_pct":        {"value": 0.08, "threshold": 0.06, "passed": True},
            "range_expansion": {"value": 1.4, "threshold": 1.25, "passed": True},
            "close_location": {"value": 0.85, "threshold": 0.60, "passed": True},
            "ema_distance":   {"value": 0.05, "threshold": 0.0, "passed": True},
            "ema_slope":      {"value": 0.02, "threshold": 0.0, "passed": True},
        },
        "selection": {
            "slot_index": slot, "slate_size": 5,
            "max_concurrent_positions": 5,
            "running_gross_at_entry": 0.0,
            "max_gross_exposure_pct": 0.50,
            "max_gross_exposure_dollars": None,
        },
        "sizing": {
            "qty": qty, "candidate_close": entry,
            "notional_at_close": entry * qty,
            "equity_at_entry": 100_000.0,
            "per_trade_pct": 0.10,
            "max_per_trade_dollars": None,
            "max_position_as_adv_frac": 0.03,
            "avg_dollar_volume": 1_000_000.0,
            "adv_cap_dollars": 30_000.0,
            "target_dollars": 10_000.0,
            "binding_cap": "per_trade_pct",
        },
        "bracket": {
            "mode": "actual_fill", "target_pct": 0.15,
            "stop_pct": 0.08, "max_hold_days": 3,
            "signal_fade_enabled": True,
        },
        "risk": {
            "daily_loss_pct": 0.03,
            "daily_pnl_baseline_equity": 100_000.0,
            "daily_pnl_tripped": False,
        },
        "intraday_confirmation": {"enabled": False, "passed": None},
        "config_hash": "test1234",
    }

    fill = {
        "record_type": "entry_fill",
        "ts": (base_ts + timedelta(seconds=2)).isoformat(),
        "ticker": ticker, "link_id": link_id,
        "filled_qty": qty,
        "filled_avg_price": entry,
        "candidate_close": entry,
        "slippage_vs_candidate_close_pct": 0.0,
        "fill_latency_seconds": 1.5,
        "partial_fill": False,
    }

    bracket_attached = {
        "record_type": "bracket_attached",
        "ts": (base_ts + timedelta(seconds=5)).isoformat(),
        "ticker": ticker, "link_id": link_id,
        "target_order_id": "T-X", "stop_order_id": "S-X",
        "target_price": target, "stop_price": stop,
        "fill_price": entry,
        "target_pct": 0.15, "stop_pct": 0.08,
    }

    # Five ticks walking the price toward exit. For a target_hit we
    # drift up; for a stop_hit we dip first then exit.
    if reason == "target_hit":
        path = [entry, entry * 1.04, entry * 1.08, entry * 1.12, exit_price]
    else:
        path = [entry, entry * 0.96, entry * 0.94, entry * 0.93, exit_price]
    peak = entry
    trough = entry
    ticks = []
    for i, mark in enumerate(path):
        peak = max(peak, mark)
        trough = min(trough, mark)
        ts = base_ts + timedelta(minutes=(i + 1))
        ticks.append({
            "record_type": "intraday_tick",
            "ts": ts.isoformat(),
            "ticker": ticker, "link_id": link_id,
            "quote": {
                "bid": mark - 0.01, "ask": mark + 0.01, "mid": mark,
                "spread": 0.02, "spread_pct": 0.02 / mark,
                "bid_size": 100, "ask_size": 100,
                "last": mark,
                "ts": ts.isoformat(),
            },
            "session_bar": {
                "open": entry, "high": peak, "low": trough,
                "close": mark, "volume": 1_000_000 * (i + 1),
                "prev_close": entry * 0.98,
                "gap_from_prev_close_pct": (entry - entry * 0.98) / (entry * 0.98),
                "intraday_range_pct": (peak - trough) / entry,
            },
            "position": {
                "qty": qty, "entry_price": entry, "mark": mark,
                "current_value": mark * qty,
                "unrealized_pnl": (mark - entry) * qty,
                "unrealized_pnl_pct": (mark - entry) / entry,
                "target_price": target, "stop_price": stop,
            },
            "excursion": {
                "peak_since_entry": peak,
                "trough_since_entry": trough,
                "mfe_dollar": (peak - entry) * qty,
                "mae_dollar": (trough - entry) * qty,
                "drawdown_from_peak_pct": (mark - peak) / peak,
                "runup_from_trough_pct": (mark - trough) / trough,
            },
            "distance": {
                "to_target_pct": (target - mark) / mark,
                "to_stop_pct": (stop - mark) / mark,
                "target_to_stop_ratio": (
                    abs((target - mark) / (stop - mark))
                    if (stop - mark) != 0 else None
                ),
            },
            "time": {
                "minutes_held": i + 1,
                "session_minutes_remaining": 389 - (i + 1),
                "entry_timestamp": base_ts.isoformat(),
            },
        })

    realized = (exit_price - entry) * qty
    exit_record = {
        "record_type": "exit",
        "ts": (base_ts + timedelta(minutes=10)).isoformat(),
        "ticker": ticker, "link_id": link_id,
        "qty": qty, "entry_price": entry, "exit_price": exit_price,
        "entry_timestamp": base_ts.isoformat(),
        "exit_timestamp": (base_ts + timedelta(minutes=10)).isoformat(),
        "realized_pnl": realized, "reason": reason,
        "hold_trading_days": 0,
        "entry_to_exit_pct": (exit_price - entry) / entry,
        "mfe_dollar": (peak - entry) * qty,
        "mae_dollar": (trough - entry) * qty,
        "mfe_pct": (peak - entry) / entry,
        "mae_pct": (trough - entry) / entry,
        "peak_since_entry": peak,
        "trough_since_entry": trough,
        "venue_code": "XNAS", "exchange": "NASDAQ",
        "signal_strength": signal_strength,
        "candidate_close": entry,
        "target_pct": 0.15, "stop_pct": 0.08,
        "target_price": target, "stop_price": stop,
        "bracket_pricing_mode": "actual_fill",
        "link_id": link_id,
    }

    return [decision, fill, bracket_attached, *ticks, exit_record]


@pytest.fixture
def trades_dir(tmp_path):
    base = datetime(2026, 5, 7, 13, 30, tzinfo=timezone.utc)
    # Winner: target_hit, slot 0
    _emit(
        tmp_path / "BOWAKA-AAPL-1.jsonl",
        _trade_records(
            ticker="AAPL", link_id="BOWAKA-AAPL-1",
            entry=100.0, exit_price=115.0, reason="target_hit", slot=0,
            base_ts=base,
        ),
    )
    # Loser: stop_hit, slot 4 (lowest signal in the slate)
    _emit(
        tmp_path / "BOWAKA-MSFT-1.jsonl",
        _trade_records(
            ticker="MSFT", link_id="BOWAKA-MSFT-1",
            entry=200.0, exit_price=184.0, reason="stop_hit", slot=4,
            signal_strength=5.5, rvol=1.6,
            base_ts=base,
        ),
    )
    return tmp_path


def test_load_records_finds_all_jsonl(analysis_module, trades_dir):
    df = analysis_module.load_records(trades_dir)
    assert not df.empty
    assert df["_source_file"].nunique() == 2
    # Every file has decision + fill + bracket + 5 ticks + exit = 9
    assert len(df) == 18


def test_to_decisions_one_per_entry_decision(analysis_module, trades_dir):
    df = analysis_module.load_records(trades_dir)
    d = analysis_module.to_decisions(df)
    assert len(d) == 2
    assert set(d["link_id"]) == {"BOWAKA-AAPL-1", "BOWAKA-MSFT-1"}
    assert "feat_rvol" in d.columns
    assert "gate_rvol_margin" in d.columns
    aapl = d[d.ticker == "AAPL"].iloc[0]
    # rvol = 2.5, threshold 1.5 -> margin 5/3
    assert abs(aapl["gate_rvol_margin"] - 2.5 / 1.5) < 1e-6


def test_to_closed_trades_joins_decision_to_exit(analysis_module, trades_dir):
    df = analysis_module.load_records(trades_dir)
    closed = analysis_module.to_closed_trades(df)
    assert len(closed) == 2
    aapl = closed[closed.ticker == "AAPL"].iloc[0]
    assert aapl["realized_pnl"] == 1500.0  # (115-100) * 100
    assert aapl["reason"] == "target_hit"
    assert aapl["slot_index"] == 0


def test_to_ticks_long_form(analysis_module, trades_dir):
    df = analysis_module.load_records(trades_dir)
    ticks = analysis_module.to_ticks(df)
    # 5 ticks per trade × 2 trades
    assert len(ticks) == 10
    assert "to_target_pct" in ticks.columns
    assert "drawdown_from_peak_pct" in ticks.columns


def test_slot_alpha_aggregates(analysis_module, trades_dir):
    df = analysis_module.load_records(trades_dir)
    closed = analysis_module.to_closed_trades(df)
    sa = analysis_module.slot_alpha(closed)
    assert set(sa["slot_index"]) == {0, 4}
    # Slot 0 winner: pnl=1500, win_rate=1; slot 4 loser: pnl=-1600, win_rate=0
    s0 = sa[sa.slot_index == 0].iloc[0]
    s4 = sa[sa.slot_index == 4].iloc[0]
    assert s0["mean_pnl"] == 1500.0
    assert s4["mean_pnl"] == -1600.0


def test_exit_reason_breakdown(analysis_module, trades_dir):
    df = analysis_module.load_records(trades_dir)
    closed = analysis_module.to_closed_trades(df)
    rb = analysis_module.exit_reason_breakdown(closed)
    assert set(rb["reason"]) == {"target_hit", "stop_hit"}


def test_drawdown_before_stop(analysis_module, trades_dir):
    df = analysis_module.load_records(trades_dir)
    closed = analysis_module.to_closed_trades(df)
    ticks = analysis_module.to_ticks(df)
    dd = analysis_module.drawdown_before_stop(ticks, closed)
    assert len(dd) == 1  # one stop_hit trade
    msft = dd.iloc[0]
    assert msft["ticker"] == "MSFT"
    # Deepest drawdown_from_peak_pct on the loss path is at the
    # exit price (mark below peak); just ensure we got a real number.
    assert msft["deepest_drawdown_pct"] is not None
    assert msft["deepest_drawdown_pct"] < 0


def test_main_runs_without_error(analysis_module, trades_dir, capsys):
    rc = analysis_module.main(["--trades-dir", str(trades_dir),
                                "--summary", str(trades_dir / "no.jsonl")])
    assert rc == 0
    captured = capsys.readouterr().out
    # Spot-check that headline sections rendered.
    assert "Slot-index alpha" in captured
    assert "Exit reason breakdown" in captured
    assert "MFE / MAE percentiles" in captured
