"""Phase 3 — full-day scanner replay integration test."""
from __future__ import annotations

import json
from pathlib import Path

import pandas as pd
import pytest

import bowaka_intraday_scanner as scanner


def _cfg() -> dict:
    return {
        "data": {"provider": "alpaca", "feed": "iex",
                  "intraday_timeframe": "1m"},
        "scanner": {
            "scan_interval_seconds": 60,
            "max_candidates_per_scan": 10,
            "signal_expiry_seconds": 600,
        },
        "signals": {
            "rvol_so_far_min": 1.0,
            "projected_full_day_rvol_min": 1.0,
            "prior_atr_pct_min": 0.0,
            "range_expansion_so_far_min": 1.0,
            "close_location_so_far_min": 0.0,
            "ema_distance_min": -1.0,
            "ema_slope_min": -1.0,
            "price_min": 1.0,
            "price_max": 100.0,
            "avg_dollar_volume_min": 1.0,
        },
        "score": {"bounded": True},
        "historical_features": {
            "volume_curve": {"bucket_edges": [
                250000, 500000, 1000000, 5000000, 20000000,
            ]},
        },
    }


def _universe(symbols) -> dict:
    return {
        "universe_hash": "sha256:test",
        "symbols": [
            {"symbol": s, "exchange": "NASDAQ", "venue_code": "XNAS",
             "instrument_class": "operating_equity",
             "eligible_for_bowaka_equity_bucket": True}
            for s in symbols
        ],
    }


def _cache(symbols) -> pd.DataFrame:
    rows = []
    for s in symbols:
        rows.append({
            "symbol": s,
            "prior_close": 10.0,
            "avg_volume_20d": 500_000,
            "avg_dollar_volume_20d": 5_000_000,
            "prior_atr_14d": 0.50,
            "prior_atr_pct": 0.05,
            "ema_10_prior": 9.50,
            "ema_10_lag_3": 9.30,
            "ema_slope_prior": 0.0215,
        })
    return pd.DataFrame(rows)


def _build_bars(symbol, scan_ts, *, range_expansion_target: float) -> pd.DataFrame:
    """Synthesize bars whose session_range = range_expansion_target *
    prior_atr_14d (0.50). Volume scales linearly with elapsed minutes
    to give RVOL_so_far ≈ 1.5."""
    start = pd.Timestamp("2026-05-18 09:30:00", tz="America/New_York")
    scan_ts_et = pd.Timestamp(scan_ts).tz_convert("America/New_York")
    elapsed = max(1, int((scan_ts_et - start).total_seconds() / 60))
    target_range = 0.50 * range_expansion_target
    rows = []
    for i in range(elapsed):
        ts = start + pd.Timedelta(minutes=i)
        rows.append({
            "timestamp": ts.tz_convert("UTC"),
            "open":  10.0,
            "high":  10.0 + target_range,
            "low":   10.0,
            "close": 10.0 + target_range,
            "volume": 5000.0,
        })
    return pd.DataFrame(rows)


def test_scanner_replay_full_day(tmp_path):
    """Replay a session with 5 symbols across 09:30→16:00.
    XYZ crosses gates only at 10:45 (range_expansion comes up).
    ABC crosses gates only at 13:20. Expect exactly two events."""
    cfg = _cfg()
    symbols = ["XYZ", "ABC", "S03", "S04", "S05"]
    universe = _universe(symbols)
    cache = _cache(symbols)

    def bars_supplier(symbol: str, scan_ts):
        scan_et = pd.Timestamp(scan_ts).tz_convert("America/New_York")
        elapsed_min = (scan_et
                       - pd.Timestamp("2026-05-18 09:30:00",
                                       tz="America/New_York")
                       ).total_seconds() / 60
        # XYZ qualifies at 10:45 ET (75 minutes in) and later;
        # ABC qualifies at 13:20 ET (230 minutes in) and later.
        # S03..S05 never qualify.
        re_target_for = {
            "XYZ": 1.5 if elapsed_min >= 75 else 0.3,
            "ABC": 1.5 if elapsed_min >= 230 else 0.3,
            "S03": 0.3, "S04": 0.3, "S05": 0.3,
        }
        return _build_bars(
            symbol, scan_ts,
            range_expansion_target=re_target_for[symbol],
        )

    state = scanner._empty_state("2026-05-18")
    cand_path = tmp_path / "candidates.jsonl"
    hb_path = tmp_path / "heartbeat.jsonl"

    # Five scan ticks across the day.
    scan_times = [
        pd.Timestamp(f"2026-05-18 {t}:00", tz="America/New_York")
                .tz_convert("UTC").to_pydatetime()
        for t in ("10:00", "10:45", "11:30", "13:20", "15:00")
    ]
    all_emitted: list[dict] = []
    for st in scan_times:
        ev_list = scanner.evaluate_one_scan(
            cfg=cfg, universe_snapshot=universe,
            daily_cache=cache, volume_curve=None,
            state=state, scan_ts=st,
            bars_supplier=bars_supplier,
            candidate_events_path=cand_path,
            heartbeat_path=hb_path,
        )
        all_emitted.extend(ev_list)

    # The contract: a symbol may be emitted multiple times across
    # ticks (signal persists). Verify both XYZ (at 10:45 + later)
    # and ABC (at 13:20 + later) appear; S03..S05 never appear.
    symbols_emitted = {ev["symbol"] for ev in all_emitted}
    assert "XYZ" in symbols_emitted
    assert "ABC" in symbols_emitted
    assert symbols_emitted & {"S03", "S04", "S05"} == set()

    # And heartbeat events landed (one per scan tick).
    hb_lines = hb_path.read_text().splitlines()
    assert len(hb_lines) == 5
