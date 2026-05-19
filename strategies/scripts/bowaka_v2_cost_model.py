#!/usr/bin/env python3
"""Bowaka v2 — transaction-cost model.

Three stress levels per handoff §8.8:
  base         half_spread + 5 bps impact
  conservative full_spread + sqrt(notional/adv)-scaled impact
  severe       full_spread + 2x impact + 10 bps adverse exit slip

Plus halt_stress (no exit until next print) and gap_stress
(overnight stop fills 50 bps worse). All functions are pure; no
I/O. Used by the Phase 5 backtester.
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Literal


StressLevel = Literal["base", "conservative", "severe"]


@dataclass
class FillResult:
    fill_price: float
    cost_bps: float
    notes: dict


def _bps_to_pct(bps: float) -> float:
    return bps / 10_000.0


def estimate_entry_fill(
    *,
    quote_bid: float,
    quote_ask: float,
    notional: float,
    avg_dollar_volume: float | None,
    stress: StressLevel = "base",
) -> FillResult:
    """Estimate a BUY entry fill given a quote and a cost stress.

    base:         pays mid + half_spread + 5 bps impact
    conservative: pays ask + impact_bps = 25 * sqrt(notional/adv)
    severe:       pays ask + 2 * impact + 10 bps adverse slip
    """
    mid = (quote_bid + quote_ask) / 2.0
    spread = quote_ask - quote_bid
    half_spread = spread / 2.0

    if stress == "base":
        impact_bps = 5.0
        fill = mid + half_spread + mid * _bps_to_pct(impact_bps)
    elif stress == "conservative":
        impact_bps = _sqrt_impact_bps(notional, avg_dollar_volume)
        fill = quote_ask + mid * _bps_to_pct(impact_bps)
    elif stress == "severe":
        impact_bps = _sqrt_impact_bps(notional, avg_dollar_volume) * 2.0
        adverse = 10.0
        fill = quote_ask + mid * _bps_to_pct(impact_bps + adverse)
    else:
        raise ValueError(f"unknown stress level: {stress!r}")
    return FillResult(
        fill_price=round(fill, 4),
        cost_bps=(fill - mid) / mid * 10_000.0 if mid > 0 else 0.0,
        notes={"stress": stress, "spread": spread, "impact_bps": impact_bps},
    )


def estimate_exit_fill(
    *,
    quote_bid: float,
    quote_ask: float,
    notional: float,
    avg_dollar_volume: float | None,
    stress: StressLevel = "base",
    halt_stress: bool = False,
    next_print_price: float | None = None,
    gap_stress_overnight_stop: bool = False,
    stop_trigger_price: float | None = None,
) -> FillResult:
    """Estimate a SELL exit fill. ``halt_stress=True`` forces the
    fill to ``next_print_price`` (caller supplies). ``gap_stress_
    overnight_stop=True`` fills the stop 50 bps worse than
    ``stop_trigger_price``."""
    mid = (quote_bid + quote_ask) / 2.0
    spread = quote_ask - quote_bid
    half_spread = spread / 2.0

    if halt_stress and next_print_price is not None:
        return FillResult(
            fill_price=round(float(next_print_price), 4),
            cost_bps=(mid - next_print_price) / mid * 10_000.0 if mid > 0 else 0.0,
            notes={"stress": stress, "halt_stress": True},
        )
    if gap_stress_overnight_stop and stop_trigger_price is not None:
        adverse = 50.0
        fill = stop_trigger_price * (1 - _bps_to_pct(adverse))
        return FillResult(
            fill_price=round(fill, 4),
            cost_bps=adverse,
            notes={"stress": stress, "gap_stress": True},
        )

    if stress == "base":
        impact_bps = 5.0
        fill = mid - half_spread - mid * _bps_to_pct(impact_bps)
    elif stress == "conservative":
        impact_bps = _sqrt_impact_bps(notional, avg_dollar_volume)
        fill = quote_bid - mid * _bps_to_pct(impact_bps)
    elif stress == "severe":
        impact_bps = _sqrt_impact_bps(notional, avg_dollar_volume) * 2.0
        adverse = 10.0
        fill = quote_bid - mid * _bps_to_pct(impact_bps + adverse)
    else:
        raise ValueError(f"unknown stress level: {stress!r}")
    return FillResult(
        fill_price=round(fill, 4),
        cost_bps=(mid - fill) / mid * 10_000.0 if mid > 0 else 0.0,
        notes={"stress": stress, "spread": spread, "impact_bps": impact_bps},
    )


def _sqrt_impact_bps(
    notional: float, avg_dollar_volume: float | None,
) -> float:
    """Square-root impact model: impact_bps = 25 * sqrt(notional /
    avg_dollar_volume). Returns 5 bps floor when ADV is missing."""
    if avg_dollar_volume is None or avg_dollar_volume <= 0 or notional <= 0:
        return 5.0
    frac = notional / avg_dollar_volume
    return 25.0 * math.sqrt(frac)
