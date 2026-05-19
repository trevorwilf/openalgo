"""Phase 5 — cost model tests."""
from __future__ import annotations

import pytest

import bowaka_v2_cost_model as cm


def test_base_stress_half_spread_plus_5bps():
    """Base: pays mid + half_spread + 5 bps impact."""
    r = cm.estimate_entry_fill(
        quote_bid=10.00, quote_ask=10.10,
        notional=5000, avg_dollar_volume=5_000_000,
        stress="base",
    )
    # mid=10.05, half_spread=0.05, impact = 5 bps of mid = 0.005025
    # → fill ≈ 10.05 + 0.05 + 0.005025 = 10.1050.
    assert r.fill_price == pytest.approx(10.1050, rel=1e-3)


def test_conservative_full_spread_plus_sqrt_impact():
    """Conservative: pays ask + sqrt-impact bps."""
    r = cm.estimate_entry_fill(
        quote_bid=10.00, quote_ask=10.10,
        notional=50_000, avg_dollar_volume=5_000_000,
        stress="conservative",
    )
    # impact_bps = 25 * sqrt(50000/5000000) = 25 * sqrt(0.01) = 2.5
    # → fill ≈ 10.10 + 10.05 * 2.5/10000 = 10.10 + 0.00251 ≈ 10.1025
    assert r.fill_price == pytest.approx(10.1025, rel=1e-3)


def test_severe_doubles_impact_plus_exit_slip():
    """Severe: 2x impact + 10 bps adverse exit slip on exits."""
    r = cm.estimate_exit_fill(
        quote_bid=10.00, quote_ask=10.10,
        notional=50_000, avg_dollar_volume=5_000_000,
        stress="severe",
    )
    # impact_bps = 25 * sqrt(0.01) * 2 = 5; adverse = 10; total = 15
    # → mid bps decline ≈ 15 bps → ~10.05 * 0.0015 ≈ 0.0151
    # fill = bid - 10.05 * 15/10000 ≈ 10.0 - 0.0151 = 9.985
    assert r.fill_price == pytest.approx(9.985, rel=1e-3)


def test_halt_stress_delays_exit_to_next_print():
    r = cm.estimate_exit_fill(
        quote_bid=10.00, quote_ask=10.10,
        notional=5000, avg_dollar_volume=5_000_000,
        stress="base",
        halt_stress=True,
        next_print_price=9.50,
    )
    assert r.fill_price == pytest.approx(9.50)
    assert r.notes.get("halt_stress") is True


def test_gap_stress_overnight_stop_fills_worse():
    r = cm.estimate_exit_fill(
        quote_bid=9.00, quote_ask=9.10,
        notional=5000, avg_dollar_volume=5_000_000,
        stress="base",
        gap_stress_overnight_stop=True,
        stop_trigger_price=9.20,
    )
    # 50 bps worse: 9.20 * (1 - 0.005) = 9.154
    assert r.fill_price == pytest.approx(9.154, rel=1e-3)
