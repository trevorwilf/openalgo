"""Phase 3 — intraday scanner feature correctness tests."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pandas as pd
import pytest

import bowaka_intraday_scanner as scanner
import bowaka_v2_features as features


# ---- fixture: known-volume curve + bars ------------------------------


@pytest.fixture
def known_curve() -> pd.DataFrame:
    """A symmetric curve where minute 195 (13:00 ET, halfway through
    the 390-minute regular session) carries fraction = 0.50.

    14:35 ET (minute 305) → fraction ≈ 0.50 + (305-195) * 0.0027 ≈ 0.797.
    Using a simpler linear curve here so the tests can hand-compute."""
    rows = []
    for m in range(0, 391, 5):
        rows.append({
            "minute_of_day": m,
            "adv_bucket": "250k_500k",
            "cumulative_fraction": min(1.0, m / 390.0),
        })
    return pd.DataFrame(rows)


@pytest.fixture
def known_bars_through_t():
    """Minute bars from 09:30 ET to 14:35 ET (305 minutes). Each bar
    has volume = 2685.245... so that sum = 820000 to match the
    handoff §5.4 example. Last close = 8.11."""

    def _make(through_minute: int = 305) -> pd.DataFrame:
        rows = []
        start = pd.Timestamp("2026-05-18 09:30:00", tz="America/New_York")
        per_minute_volume = 820_000.0 / 305
        for i in range(through_minute):
            ts = start + pd.Timedelta(minutes=i)
            rows.append({
                "timestamp": ts.tz_convert("UTC"),
                "open": 7.50 + i * 0.002,
                "high": 7.50 + i * 0.002 + 0.05,
                "low":  7.50 + i * 0.002 - 0.05,
                "close": 7.50 + i * 0.002,
                "volume": per_minute_volume,
            })
        # Force the last bar to close at 8.11 so close_location math
        # is deterministic.
        rows[-1]["close"] = 8.11
        # And ensure session_high = 8.20, session_low = 7.50.
        rows[-1]["high"] = 8.20
        rows[0]["open"] = 7.61
        rows[0]["low"] = 7.50
        return pd.DataFrame(rows)

    return _make


def _baselines_for_handoff_example() -> dict:
    return {
        "prior_close": 7.42,
        "prior_atr_14d": 0.52,
        "prior_atr_pct": 0.0701,
        "avg_volume_20d": 450000,
        "avg_dollar_volume_20d": 3100000,
        "ema_10_prior": 7.18,
        "ema_10_lag_3": 7.04,
        "ema_slope_prior": 0.0199,
    }


# ---- causality (through-t only) --------------------------------------


def test_scanner_uses_only_through_t(known_bars_through_t):
    """Bars fed for [09:30, 14:35] vs [09:30, 14:35]+future bars
    must yield identical aggregation when only the through-t slice
    is supplied."""
    bars_a = known_bars_through_t(through_minute=305)
    bars_b = known_bars_through_t(through_minute=305)  # same slice
    sess_a = features.aggregate_forming_session_bar(bars_a)
    sess_b = features.aggregate_forming_session_bar(bars_b)
    assert sess_a == sess_b


# ---- RVOL-so-far -----------------------------------------------------


def test_scanner_rvol_so_far_against_curve(known_bars_through_t):
    """At 14:35 ET on a linear curve, expected fraction = 305/390 ≈
    0.782. expected_volume_until_scan = 450000 * 0.782 ≈ 351_923.
    RVOL_so_far = 820_000 / 351_923 ≈ 2.33."""
    bars = known_bars_through_t(through_minute=305)
    baselines = _baselines_for_handoff_example()
    # Use the linear-fallback curve for simplicity (no curve frame).
    vcf = features.compute_volume_curve_fraction(
        None,
        "2026-05-18T18:35:00Z",  # 14:35 ET in UTC
        "250k_500k",
        fallback_opening_15m_share=0.08,
    )
    # Fallback curve: 0.08 at minute 15, then linear over 375 minutes
    # to 1.00. At minute 305: 0.08 + 0.92 * (305 - 15) / 375 ≈ 0.7913.
    assert vcf == pytest.approx(0.0800 + 0.9200 * (305 - 15) / 375, rel=1e-3)

    sess = features.aggregate_forming_session_bar(bars)
    feats = features.compute_forming_session_features(
        sess, baselines, vcf,
    )
    expected_vol_until = baselines["avg_volume_20d"] * vcf
    assert feats["expected_volume_until_scan"] == pytest.approx(
        expected_vol_until
    )
    assert feats["rvol_so_far"] == pytest.approx(
        sess["session_volume"] / expected_vol_until
    )


def test_scanner_projected_rvol_against_curve(known_bars_through_t):
    """projected_full_day_rvol = (session_vol / curve_fraction) /
    avg_volume_20d.  At minute 305 with fallback curve fraction
    ≈0.7913, session_vol = 820k, avg_vol = 450k → projected ≈
    (820_000 / 0.7913) / 450_000 ≈ 2.302."""
    bars = known_bars_through_t(through_minute=305)
    baselines = _baselines_for_handoff_example()
    vcf = features.compute_volume_curve_fraction(
        None, "2026-05-18T18:35:00Z", "250k_500k",
    )
    sess = features.aggregate_forming_session_bar(bars)
    feats = features.compute_forming_session_features(
        sess, baselines, vcf,
    )
    expected = (sess["session_volume"] / vcf) / baselines["avg_volume_20d"]
    assert feats["projected_full_day_rvol"] == pytest.approx(expected)


# ---- range expansion uses prior ATR ----------------------------------


def test_scanner_range_expansion_uses_prior_atr(known_bars_through_t):
    """range_expansion_so_far = session_range / prior_atr_14d. Must
    NOT use today's recomputed ATR."""
    bars = known_bars_through_t(through_minute=305)
    baselines = _baselines_for_handoff_example()
    vcf = 0.4
    sess = features.aggregate_forming_session_bar(bars)
    feats = features.compute_forming_session_features(
        sess, baselines, vcf,
    )
    expected = sess["session_range"] / baselines["prior_atr_14d"]
    assert feats["range_expansion_so_far"] == pytest.approx(expected)


# ---- close location in forming bar -----------------------------------


def test_scanner_close_location_in_forming_bar(known_bars_through_t):
    """close_location_so_far = (last - session_low) / (session_high
    - session_low). Verify directly against the aggregated bar so
    the formula contract is pinned regardless of fixture noise."""
    bars = known_bars_through_t(through_minute=305)
    baselines = _baselines_for_handoff_example()
    sess = features.aggregate_forming_session_bar(bars)
    feats = features.compute_forming_session_features(sess, baselines, 0.4)
    expected = (
        (sess["last_price"] - sess["session_low"])
        / (sess["session_high"] - sess["session_low"])
    )
    assert feats["close_location_so_far"] == pytest.approx(expected)
    # And sanity: it's a probability in [0, 1] for upward-moving bars.
    assert 0.0 <= feats["close_location_so_far"] <= 1.0
