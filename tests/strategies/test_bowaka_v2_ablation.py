"""Phase 5 — ablation harness tests."""
from __future__ import annotations

import pandas as pd
import pytest

import bowaka_v2_backtest as backtest
import bowaka_v2_ablation as ablation


def _cfg() -> dict:
    return {
        "scanner": {"scan_interval_seconds": 300,
                      "max_candidates_per_scan": 5},
        "signals": {
            "rvol_so_far_min": 1.0,
            "projected_full_day_rvol_min": 1.0,
            "prior_atr_pct_min": 0.0,
            "range_expansion_so_far_min": 1.0,
            "close_location_so_far_min": 0.0,
            "ema_distance_min": -1.0,
            "ema_slope_min": -1.0,
            "price_min": 1.0, "price_max": 100.0,
            "avg_dollar_volume_min": 1.0,
        },
        "score": {"bounded": True},
        "sizing": {
            "bankroll_fixed_dollars": 90000,
            "max_concurrent_positions": 18,
            "equal_slice_bankroll_fraction": 0.80,
        },
        "exits": {"stop_pct": 0.08, "target_pct": 0.15, "max_hold_days": 3},
        "risk": {"max_total_entries_per_day": 10},
    }


def test_apply_ablation_removes_signal_gates():
    sigs = {
        "rvol_so_far_min": 1.5, "projected_full_day_rvol_min": 1.5,
        "range_expansion_so_far_min": 1.25,
    }
    out = backtest._apply_ablation(sigs, "remove_volume_gate")
    assert out["rvol_so_far_min"] is None
    assert out["projected_full_day_rvol_min"] is None
    assert out["range_expansion_so_far_min"] == 1.25


def test_delay_entry_5m_shifts_fill_minutes():
    assert backtest._ablation_delay_minutes("delay_entry_5m") == 5
    assert backtest._ablation_delay_minutes("delay_entry_30m") == 30
    assert backtest._ablation_delay_minutes("none") == 0


def test_remove_volume_gate_admits_more_candidates(tmp_path):
    """The same fixture with rvol_so_far_min=null produces >= as
    many trades as with the gate active."""
    cfg = _cfg()
    cfg["signals"]["rvol_so_far_min"] = 5.0  # tight, blocks most
    cfg["signals"]["projected_full_day_rvol_min"] = 5.0

    trades_gated, _ = backtest.run_backtest(
        cfg=cfg, sessions=["2026-05-15"], symbols=["AAA"],
        minute_bars_supplier=backtest._synth_minute_bars,
        daily_bars_supplier=backtest._synth_daily_bars,
    )
    trades_ablated, _ = backtest.run_backtest(
        cfg=cfg, sessions=["2026-05-15"], symbols=["AAA"],
        minute_bars_supplier=backtest._synth_minute_bars,
        daily_bars_supplier=backtest._synth_daily_bars,
        ablation="remove_volume_gate",
    )
    assert len(trades_ablated) >= len(trades_gated)


def test_ablation_suite_writes_one_subdir_per_ablation(tmp_path):
    cfg = _cfg()
    res = ablation.run_ablation_suite(
        cfg=cfg, sessions=["2026-05-15"], symbols=["AAA"],
        minute_bars_supplier=backtest._synth_minute_bars,
        daily_bars_supplier=backtest._synth_daily_bars,
        ablations=["none", "remove_volume_gate"],
        cost_stress="base",
        output_dir=tmp_path,
    )
    assert "none" in res and "remove_volume_gate" in res
    assert (tmp_path / "none").is_dir()
    assert (tmp_path / "remove_volume_gate").is_dir()
    assert (tmp_path / "ablation_summary.json").exists()
