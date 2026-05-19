"""Phase 3 — scanner candidate emission semantics."""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pandas as pd
import pytest

import bowaka_intraday_scanner as scanner
import bowaka_v2_schemas as schemas


def _baseline_cfg() -> dict:
    return {
        "data": {"provider": "alpaca", "feed": "iex",
                  "intraday_timeframe": "1m"},
        "scanner": {
            "scan_interval_seconds": 60,
            "max_candidates_per_scan": 3,
            "signal_expiry_seconds": 600,
            "same_symbol_entries_per_day": 1,
        },
        "signals": {
            "rvol_so_far_min": 1.0,
            "projected_full_day_rvol_min": 1.0,
            "prior_atr_pct_min": 0.0,
            "range_expansion_so_far_min": 0.0,
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


def _baseline_universe(symbols) -> dict:
    return {
        "universe_hash": "sha256:test",
        "symbols": [
            {"symbol": s, "exchange": "NASDAQ", "venue_code": "XNAS",
             "instrument_class": "operating_equity",
             "eligible_for_bowaka_equity_bucket": True}
            for s in symbols
        ],
    }


def _baseline_cache(symbols) -> pd.DataFrame:
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


def _bars_for(symbol, scan_ts: datetime, *, last_close: float = 11.0,
              session_vol: float = 1_000_000.0) -> pd.DataFrame:
    """A 305-minute synthetic forming bar ending at 14:35 ET."""
    rows = []
    start = pd.Timestamp("2026-05-18 09:30:00", tz="America/New_York")
    n = 305
    per_minute_volume = session_vol / n
    for i in range(n):
        ts = start + pd.Timedelta(minutes=i)
        rows.append({
            "timestamp": ts.tz_convert("UTC"),
            "open":  10.0,
            "high":  11.0,
            "low":   9.9,
            "close": 10.5 if i < n - 1 else last_close,
            "volume": per_minute_volume,
        })
    return pd.DataFrame(rows)


# ---- emission --------------------------------------------------------


def test_scanner_emits_valid_candidate_event(tmp_path):
    cfg = _baseline_cfg()
    universe = _baseline_universe(["AAA"])
    cache = _baseline_cache(["AAA"])
    state = scanner._empty_state("2026-05-18")
    scan_ts = pd.Timestamp("2026-05-18 14:35:00",
                            tz="America/New_York").tz_convert("UTC").to_pydatetime()
    events_path = tmp_path / "candidates.jsonl"
    heartbeat_path = tmp_path / "heartbeat.jsonl"
    out = scanner.evaluate_one_scan(
        cfg=cfg, universe_snapshot=universe,
        daily_cache=cache, volume_curve=None,
        state=state, scan_ts=scan_ts,
        bars_supplier=lambda sym, ts: _bars_for(sym, ts),
        candidate_events_path=events_path,
        heartbeat_path=heartbeat_path,
    )
    assert len(out) == 1
    lines = events_path.read_text().splitlines()
    assert len(lines) == 1
    ev = json.loads(lines[0])
    ok, problems = schemas.validate_candidate_event(ev)
    assert ok, problems
    assert ev["symbol"] == "AAA"


def test_scanner_respects_max_candidates_per_scan(tmp_path):
    """10 passing symbols + max_candidates_per_scan=3 → 3 events
    emitted, ranked by signal_strength (high → low)."""
    cfg = _baseline_cfg()
    symbols = [f"S{i:02d}" for i in range(10)]
    universe = _baseline_universe(symbols)
    cache = _baseline_cache(symbols)
    # Give each symbol a different last_close so the score varies.
    closes = {s: 10.0 + i * 0.2 for i, s in enumerate(symbols)}
    state = scanner._empty_state("2026-05-18")
    scan_ts = pd.Timestamp("2026-05-18 14:35:00",
                            tz="America/New_York").tz_convert("UTC").to_pydatetime()
    events_path = tmp_path / "candidates.jsonl"
    out = scanner.evaluate_one_scan(
        cfg=cfg, universe_snapshot=universe,
        daily_cache=cache, volume_curve=None,
        state=state, scan_ts=scan_ts,
        bars_supplier=lambda sym, ts: _bars_for(
            sym, ts, last_close=closes[sym],
        ),
        candidate_events_path=events_path,
        heartbeat_path=tmp_path / "hb.jsonl",
    )
    assert len(out) == 3
    # Verify ranks are 1, 2, 3.
    ranks = [ev["candidate_rank"] for ev in out]
    assert ranks == [1, 2, 3]
    # Highest signal_strength first.
    strengths = [ev["features"]["signal_strength"] for ev in out]
    assert strengths == sorted(strengths, reverse=True)


def test_scanner_per_symbol_cooldown(tmp_path):
    """Symbol already in ``entered_symbols_today`` MUST not appear
    in candidate emission."""
    cfg = _baseline_cfg()
    universe = _baseline_universe(["AAA", "BBB"])
    cache = _baseline_cache(["AAA", "BBB"])
    state = scanner._empty_state("2026-05-18")
    state["entered_symbols_today"] = ["AAA"]
    scan_ts = pd.Timestamp("2026-05-18 14:35:00",
                            tz="America/New_York").tz_convert("UTC").to_pydatetime()
    out = scanner.evaluate_one_scan(
        cfg=cfg, universe_snapshot=universe,
        daily_cache=cache, volume_curve=None,
        state=state, scan_ts=scan_ts,
        bars_supplier=lambda sym, ts: _bars_for(sym, ts),
        candidate_events_path=tmp_path / "c.jsonl",
        heartbeat_path=tmp_path / "hb.jsonl",
    )
    emitted_symbols = {ev["symbol"] for ev in out}
    assert "AAA" not in emitted_symbols
    assert "BBB" in emitted_symbols


def test_scanner_signal_expiry_set_correctly(tmp_path):
    """signal_expiry_timestamp = scan_timestamp + signal_expiry_seconds."""
    cfg = _baseline_cfg()
    cfg["scanner"]["signal_expiry_seconds"] = 300
    universe = _baseline_universe(["AAA"])
    cache = _baseline_cache(["AAA"])
    state = scanner._empty_state("2026-05-18")
    scan_ts = pd.Timestamp("2026-05-18 14:35:00",
                            tz="America/New_York").tz_convert("UTC").to_pydatetime()
    out = scanner.evaluate_one_scan(
        cfg=cfg, universe_snapshot=universe,
        daily_cache=cache, volume_curve=None,
        state=state, scan_ts=scan_ts,
        bars_supplier=lambda sym, ts: _bars_for(sym, ts),
        candidate_events_path=tmp_path / "c.jsonl",
        heartbeat_path=tmp_path / "hb.jsonl",
    )
    ev = out[0]
    expiry = pd.Timestamp(ev["signal_expiry_timestamp"])
    scan = pd.Timestamp(ev["scan_timestamp"])
    assert (expiry - scan).total_seconds() == pytest.approx(300, abs=1)


def test_scanner_emits_no_event_when_no_gates_pass(tmp_path):
    """High signal thresholds → 0 events written; no candidate file
    extension."""
    cfg = _baseline_cfg()
    cfg["signals"]["rvol_so_far_min"] = 100.0  # impossible
    universe = _baseline_universe(["AAA"])
    cache = _baseline_cache(["AAA"])
    state = scanner._empty_state("2026-05-18")
    scan_ts = pd.Timestamp("2026-05-18 14:35:00",
                            tz="America/New_York").tz_convert("UTC").to_pydatetime()
    events_path = tmp_path / "candidates.jsonl"
    out = scanner.evaluate_one_scan(
        cfg=cfg, universe_snapshot=universe,
        daily_cache=cache, volume_curve=None,
        state=state, scan_ts=scan_ts,
        bars_supplier=lambda sym, ts: _bars_for(sym, ts),
        candidate_events_path=events_path,
        heartbeat_path=tmp_path / "hb.jsonl",
    )
    assert out == []
    # File not created or empty.
    assert not events_path.exists() or events_path.read_text() == ""
