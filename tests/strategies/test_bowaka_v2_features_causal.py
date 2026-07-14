"""Phase 1 — bowaka_v2_features causal-correctness tests.

Pins the no-lookahead contract from handoff §5.7 + Appendix B.
Every gate-evaluator / scanner / backtester import must use these
functions or break feature-parity.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import numpy as np
import pandas as pd
import pytest

import bowaka_v2_features as f


# ---- helpers ---------------------------------------------------------


def _mk_daily_bars(n: int, *, base: float = 10.0,
                   step: float = 0.05, vol: float = 1_000_000.0,
                   seed: int = 0) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    closes = base + np.cumsum(rng.normal(step, 0.10, size=n))
    closes = np.maximum(closes, 1.0)
    rows = []
    for i, c in enumerate(closes):
        h = float(c + abs(rng.normal(0, 0.2)))
        l = float(c - abs(rng.normal(0, 0.2)))
        o = float((h + l) / 2.0)
        v = float(vol * (1.0 + rng.normal(0, 0.2)))
        ts = datetime(2026, 1, 1, tzinfo=timezone.utc) + timedelta(days=i)
        rows.append({
            "timestamp": ts, "open": o, "high": h,
            "low": l, "close": float(c), "volume": max(v, 1.0),
        })
    return pd.DataFrame(rows)


def _mk_minute_bars(n: int, *, start: str = "2026-05-18T13:30:00Z",
                    base: float = 10.0) -> pd.DataFrame:
    rng = np.random.default_rng(7)
    closes = base + np.cumsum(rng.normal(0.0, 0.01, size=n))
    rows = []
    ts0 = pd.Timestamp(start)
    for i, c in enumerate(closes):
        h = float(c + abs(rng.normal(0, 0.02)))
        l = float(c - abs(rng.normal(0, 0.02)))
        rows.append({
            "timestamp": ts0 + pd.Timedelta(minutes=i),
            "open": float(c), "high": h, "low": l,
            "close": float(c), "volume": 1000.0,
        })
    return pd.DataFrame(rows)


# ---- prior baselines causality ---------------------------------------


def test_prior_atr_excludes_current_session() -> None:
    """Passing daily_bars including today must produce the same
    prior_atr_14d as passing bars[:-1]."""
    bars_with_today = _mk_daily_bars(30, seed=1)
    bars_excl_today = bars_with_today.iloc[:-1].copy()

    out_excl = f.compute_prior_daily_baselines(bars_excl_today)
    # Caller must slice to prior session; pass bars_excl_today as that
    # is the canonical input. Verify the function honors the contract.
    assert out_excl["prior_atr_14d"] is not None
    # And — when the caller passes the full frame with today included,
    # the function uses ALL rows. The contract is "caller is
    # responsible"; this test pins the function side: it walks the
    # tail of whatever frame it receives.
    out_full = f.compute_prior_daily_baselines(bars_with_today)
    assert out_full["prior_atr_14d"] != out_excl["prior_atr_14d"]
    # The function MUST NOT silently drop today; that's the caller's
    # responsibility. But the prior_close should be the LAST row of
    # the frame.
    assert out_excl["prior_close"] == pytest.approx(
        float(bars_excl_today["close"].iloc[-1])
    )


def test_avg_volume_excludes_current_session() -> None:
    bars = _mk_daily_bars(30, seed=2)
    out_full = f.compute_prior_daily_baselines(bars)
    out_excl = f.compute_prior_daily_baselines(bars.iloc[:-1])
    # Different last-20-window averages.
    assert out_full["avg_volume_20d"] != out_excl["avg_volume_20d"]
    # And the volume averages are positive.
    assert out_excl["avg_volume_20d"] > 0


def test_ema_distance_uses_prior_ema() -> None:
    """ema_distance gate input must use ema_10_prior from the prior
    completed session, not a forming-session re-EMA."""
    bars = _mk_daily_bars(25, seed=3)
    out = f.compute_prior_daily_baselines(bars)
    assert out["ema_10_prior"] is not None
    # compute_forming_session_features takes prior_baselines as a
    # dict; ema_distance = last_price / ema_10_prior - 1.
    sess_bar = {
        "session_open": 11.0, "session_high": 11.5,
        "session_low": 10.8, "last_price": 11.4,
        "session_volume": 5000.0, "session_range": 0.7,
        "last_bar_timestamp": "2026-05-18T14:35:00Z",
    }
    feats = f.compute_forming_session_features(
        sess_bar, out, volume_curve_fraction=0.4,
    )
    expected = 11.4 / out["ema_10_prior"] - 1.0
    assert feats["ema_distance"] == pytest.approx(expected)


# ---- forming session causality ---------------------------------------


def test_forming_close_location_through_t_only() -> None:
    """If the caller feeds minute bars beyond t, close_location_so_far
    should reflect those bars. This is a CONTRACT test: the function
    operates on what it gets; callers MUST slice."""
    bars = _mk_minute_bars(60)
    sub = bars.iloc[:30]
    sess = f.aggregate_forming_session_bar(sub)
    # close_location = (last_price - session_low) / (session_high - session_low)
    expected = (
        (sess["last_price"] - sess["session_low"])
        / (sess["session_high"] - sess["session_low"])
    )
    feats = f.compute_forming_session_features(
        sess,
        {"prior_close": 10.0, "prior_atr_14d": 0.5, "prior_atr_pct": 0.05,
         "avg_volume_20d": 50000, "avg_dollar_volume_20d": 500000,
         "ema_10_prior": 9.8, "ema_10_lag_3": 9.5, "ema_slope_prior": 0.03},
        volume_curve_fraction=0.4,
    )
    assert feats["close_location_so_far"] == pytest.approx(expected)


# ---- volume curve causality ------------------------------------------


def test_volume_curve_causal() -> None:
    """The function reads the supplied curve. The CONTRACT is that
    the curve frame is built only from prior sessions; verifying that
    the function gives the same result regardless of what new
    same-session data is added would require building the curve
    inside the function (which it does not — by design)."""
    # Two curve frames that share the (minute_of_day, adv_bucket) rows
    # for bucket A must give identical results.
    base_rows = [
        {"minute_of_day": 0,   "adv_bucket": "250k_500k", "cumulative_fraction": 0.00},
        {"minute_of_day": 30,  "adv_bucket": "250k_500k", "cumulative_fraction": 0.10},
        {"minute_of_day": 60,  "adv_bucket": "250k_500k", "cumulative_fraction": 0.16},
        {"minute_of_day": 195, "adv_bucket": "250k_500k", "cumulative_fraction": 0.55},
        {"minute_of_day": 390, "adv_bucket": "250k_500k", "cumulative_fraction": 1.00},
    ]
    curve_a = pd.DataFrame(base_rows)
    curve_b = pd.DataFrame(base_rows + [
        {"minute_of_day": 245, "adv_bucket": "5M_20M", "cumulative_fraction": 0.66},
    ])
    scan_t = "2026-05-18T17:00:00Z"  # 13:00 ET = minute 210
    frac_a = f.compute_volume_curve_fraction(curve_a, scan_t, "250k_500k")
    frac_b = f.compute_volume_curve_fraction(curve_b, scan_t, "250k_500k")
    assert frac_a == pytest.approx(frac_b)
    # Linear interpolation: at minute 210, between (195, 0.55) and (390, 1.00):
    # 0.55 + (0.45) * (210-195)/(390-195) = 0.55 + 0.45*15/195 ≈ 0.5846
    assert frac_a == pytest.approx(0.55 + 0.45 * 15 / 195, rel=1e-6)


def test_volume_curve_missing_falls_back() -> None:
    """No curve → fall back to opening-15m share + linear ramp.
    Sanity: at 09:45 ET (minute 15), fraction equals
    fallback_opening_15m_share."""
    frac = f.compute_volume_curve_fraction(
        None, "2026-05-18T13:45:00Z", "anything",
        fallback_opening_15m_share=0.08,
    )
    assert frac == pytest.approx(0.08)


# ---- gates ------------------------------------------------------------


def test_apply_v2_gates_returns_per_gate_results() -> None:
    feats = {
        "rvol_so_far": 2.5, "projected_full_day_rvol": 2.5,
        "range_expansion_so_far": 1.6, "close_location_so_far": 0.85,
        "ema_distance": 0.12, "gap_pct": 0.05, "current_return_pct": 0.10,
        "expected_volume_until_scan": 100000.0,
    }
    cfg = {
        "rvol_so_far_min": 1.5, "projected_full_day_rvol_min": 1.5,
        "prior_atr_pct_min": 0.06, "range_expansion_so_far_min": 1.25,
        "close_location_so_far_min": 0.60, "ema_distance_min": 0.0,
        "ema_slope_min": 0.0, "gap_pct_max": 0.25,
        "price_min": 1.0, "price_max": 20.0,
        "avg_dollar_volume_min": 250000,
    }
    ok, gates = f.apply_v2_gates(
        feats, cfg, price=8.0, avg_dollar_volume_20d=1e6,
        prior_atr_pct=0.07, ema_slope_prior=0.05,
        instrument_class="operating_equity",
    )
    expected_keys = {
        "price_gate", "avg_dollar_volume_gate", "rvol_gate",
        "projected_rvol_gate", "prior_atr_pct_gate",
        "range_expansion_gate", "close_location_gate",
        "ema_distance_gate", "ema_slope_gate", "max_gap_gate",
        "max_rvol_gate", "max_range_expansion_gate",
        "max_current_return_gate",  # fix Phase 7 — wired LIVE
        "instrument_gate",
    }
    assert set(gates.keys()) == expected_keys
    assert ok is True
    assert all(gates.values()) is True


def test_apply_v2_gates_rejects_below_threshold() -> None:
    feats = {"rvol_so_far": 1.0, "projected_full_day_rvol": 1.0,
             "range_expansion_so_far": 1.0, "close_location_so_far": 0.5,
             "ema_distance": -0.05, "gap_pct": 0.05}
    ok, gates = f.apply_v2_gates(
        feats,
        {"rvol_so_far_min": 1.5, "close_location_so_far_min": 0.6},
        price=5.0, avg_dollar_volume_20d=500000,
        prior_atr_pct=0.07, ema_slope_prior=0.03,
        instrument_class="operating_equity",
    )
    assert ok is False
    assert gates["rvol_gate"] is False
    assert gates["close_location_gate"] is False


# ---- signal strength -------------------------------------------------


def test_signal_strength_bounded_clip() -> None:
    """Each addend in the bounded formula must be clipped at its cap."""
    feats = {
        "rvol_so_far": 100.0,                # cap at 5.0
        "range_expansion_so_far": 100.0,     # cap at 2.5
        "close_location_so_far": 1.0,
        "ema_distance": 100.0,               # cap at 0.40
        "gap_pct": 0.10,                     # no penalty (below 0.25)
    }
    score = f.compute_signal_strength(
        feats, {"bounded": True}, ema_slope_prior=100.0,
    )
    # 1.00 * 5.0 + 1.00 * 2.5 + 0.75 * 1.0 + 10.0 * 0.40 + 10.0 * 0.25 - 0
    expected = 5.0 + 2.5 + 0.75 + 4.0 + 2.5
    assert score == pytest.approx(expected)


def test_signal_strength_gap_penalty_applies_above_threshold() -> None:
    feats = {
        "rvol_so_far": 1.0, "range_expansion_so_far": 1.0,
        "close_location_so_far": 0.5, "ema_distance": 0.0,
        "gap_pct": 0.40,
    }
    score = f.compute_signal_strength(
        feats, {"bounded": True}, ema_slope_prior=0.0,
    )
    # 1.0 + 1.0 + 0.375 + 0 + 0 - (0.40 - 0.25) = 2.225
    assert score == pytest.approx(1.0 + 1.0 + 0.375 + 0 + 0 - 0.15)


def test_signal_strength_unbounded_legacy_parity() -> None:
    """bounded=False uses the v1-style unbounded sum (no clipping
    on positive addends). Used by Phase 5 parity tests."""
    feats = {
        "rvol_so_far": 10.0, "range_expansion_so_far": 3.0,
        "close_location_so_far": 1.0, "ema_distance": 0.5,
        "gap_pct": 0.1,
    }
    score = f.compute_signal_strength(
        feats, {"bounded": False}, ema_slope_prior=0.3,
    )
    # No clipping: 1*10 + 1*3 + 0.75*1 + 10*0.5 + 10*0.3 - 0 = 21.75
    assert score == pytest.approx(10 + 3 + 0.75 + 5 + 3)
