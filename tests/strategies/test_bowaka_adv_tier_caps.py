"""Tests for ADV-tier position caps.

Covers:
- ``adv_tier_cap`` helper truth table (rejection, tier boundaries,
  catch-all, back-compat fall-through to ``max_position_as_adv_frac``).
- Integration with ``select_entries`` so a rejected ADV drops the
  candidate, and capped ADV produces qty that respects the cap.
- Legacy flat cap still works when ``adv_tier_caps`` is empty or
  absent.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import pytest


# ---------------------------------------------------------------- helpers


# The canonical tier YAML matches the values in bowaka_strategy.yaml.
TIER_CFG: dict = {"risk": {"adv_tier_caps": [
    {"max_adv_dollars": 250000, "reject_if_below": True},
    {"max_adv_dollars": 500000, "max_position_as_adv_frac": 0.003},
    {"max_adv_dollars": 1000000, "max_position_as_adv_frac": 0.005},
    {"max_adv_dollars": 5000000, "max_position_as_adv_frac": 0.010},
    {"max_adv_dollars": None, "max_position_as_adv_frac": 0.015},
]}}


# ---------------------------------------------------------------- direct helper tests


@pytest.mark.parametrize("adv,expected_allowed,expected_dollars", [
    (None,        False, 0.0),
    (0,           False, 0.0),
    (-1,          False, 0.0),
    (100_000,     False, 0.0),                # below $250k → reject tier
    (250_000,     False, 0.0),                # at boundary, lands in reject tier
    (250_001,     True,  250_001 * 0.003),
    (400_000,     True,  400_000 * 0.003),
    (500_000,     True,  500_000 * 0.003),    # at $500k boundary → 0.3% tier
    (500_001,     True,  500_001 * 0.005),
    (750_000,     True,  750_000 * 0.005),
    (1_000_000,   True,  1_000_000 * 0.005),
    (1_000_001,   True,  1_000_001 * 0.010),
    (3_000_000,   True,  3_000_000 * 0.010),
    (5_000_000,   True,  5_000_000 * 0.010),
    (5_000_001,   True,  5_000_001 * 0.015),
    (50_000_000,  True,  50_000_000 * 0.015),
])
def test_adv_tier_cap_tiered(strategy_module, adv, expected_allowed, expected_dollars):
    allowed, dollars = strategy_module.adv_tier_cap(adv, TIER_CFG)
    assert allowed is expected_allowed
    assert dollars == pytest.approx(expected_dollars)


# ---------------------------------------------------------------- back-compat fall-through


def test_adv_tier_cap_falls_back_to_flat_when_list_missing(strategy_module):
    cfg = {"risk": {"max_position_as_adv_frac": 0.03}}
    allowed, dollars = strategy_module.adv_tier_cap(1_000_000, cfg)
    assert allowed is True
    assert dollars == pytest.approx(30_000.0)


def test_adv_tier_cap_falls_back_to_flat_when_list_empty(strategy_module):
    cfg = {"risk": {"max_position_as_adv_frac": 0.03, "adv_tier_caps": []}}
    allowed, dollars = strategy_module.adv_tier_cap(1_000_000, cfg)
    assert allowed is True
    assert dollars == pytest.approx(30_000.0)


def test_adv_tier_cap_no_flat_no_tiers_returns_zero(strategy_module):
    """Neither tiers nor flat frac configured → allowed but no cap.
    Calling code interprets 0.0 as "no cap"."""
    cfg = {"risk": {}}
    allowed, dollars = strategy_module.adv_tier_cap(1_000_000, cfg)
    assert allowed is True
    assert dollars == 0.0


def test_adv_tier_cap_falls_back_when_risk_missing(strategy_module):
    """No risk block at all → allowed with 0.0 cap."""
    cfg: dict = {}
    allowed, dollars = strategy_module.adv_tier_cap(1_000_000, cfg)
    assert allowed is True
    assert dollars == 0.0


def test_adv_tier_cap_no_adv_rejects_regardless_of_config(strategy_module):
    """Unknown ADV → reject even when the legacy flat cap is set."""
    cfg = {"risk": {"max_position_as_adv_frac": 0.03}}
    allowed, dollars = strategy_module.adv_tier_cap(None, cfg)
    assert allowed is False
    assert dollars == 0.0


def test_adv_tier_cap_tier_without_frac_treats_as_no_cap(strategy_module):
    """A tier with neither ``reject_if_below`` nor
    ``max_position_as_adv_frac`` is allowed-but-uncapped (0.0)."""
    cfg = {"risk": {"adv_tier_caps": [
        {"max_adv_dollars": None},   # malformed catch-all
    ]}}
    allowed, dollars = strategy_module.adv_tier_cap(1_000_000, cfg)
    assert allowed is True
    assert dollars == 0.0


# ---------------------------------------------------------------- select_entries integration


def _build_cfg(cfg_with_paths, *, with_tiers: bool) -> dict:
    """Helper: clone the conftest cfg fixture, force equal-slice
    sizing OFF (so each candidate's qty is driven purely by
    per_trade_pct × equity, then capped by ADV), and either set or
    clear the adv_tier_caps block."""
    cfg = json.loads(json.dumps(cfg_with_paths))  # deep copy
    cfg["sizing"] = {
        **cfg.get("sizing", {}),
        "per_trade_pct": 0.10,
        "max_concurrent_positions": 5,
        "default_venue_code": "XNAS",
        # Disable equal-slice so per_trade_pct × equity is the natural
        # starting qty; the ADV cap then binds.
        "equal_slice_per_position": False,
        "sizing_mode": "equal_slice",
    }
    cfg["risk"] = {
        **cfg.get("risk", {}),
        "max_position_as_adv_frac": 0.03,    # legacy flat fallback
        "max_gross_exposure_pct": 1.0,        # don't gate on gross here
    }
    if with_tiers:
        cfg["risk"]["adv_tier_caps"] = TIER_CFG["risk"]["adv_tier_caps"]
    else:
        cfg["risk"].pop("adv_tier_caps", None)
    return cfg


def _build_candidate(strategy_module, ticker: str, adv: float):
    return strategy_module.Candidate(
        ticker=ticker,
        close=10.0,
        signal_strength=5.0,
        venue_code="XNAS",
        exchange="NASDAQ",
        features={"avg_dollar_volume": adv},
    )


def test_select_entries_rejects_thinnest_tier(strategy_module, cfg_with_paths):
    """A $200k ADV candidate (below $250k reject_if_below) is dropped
    from the slate entirely; the tier rejection emits a Phase 1.4
    entry_decision with reason='adv_tier_reject'."""
    cfg = _build_cfg(cfg_with_paths, with_tiers=True)
    state = strategy_module.blank_state()
    candidates = [_build_candidate(strategy_module, "THIN", 200_000.0)]
    selected = strategy_module.select_entries(
        candidates, state, equity=1_000_000.0, latest_prices={},
        cfg=cfg, kill_state=strategy_module.KillLevel.NONE,
    )
    assert selected == []
    # Verify the rejection event made it to the canonical ledger.
    ledger_path = (
        Path(cfg["paths"]["daily_summary_path"]).parent / "trade_ledger.jsonl"
    )
    events = []
    for line in ledger_path.read_text().splitlines():
        if not line.strip():
            continue
        events.append(json.loads(line))
    reasons = {
        e["payload"]["ticker"]: e["payload"]["reason"]
        for e in events if e["event_type"] == "entry_decision"
    }
    assert reasons["THIN"] == "adv_tier_reject"


def test_select_entries_caps_at_0_5_percent_tier(
    strategy_module, cfg_with_paths,
):
    """A $700k ADV candidate (lands in the $500k–$1M tier at 0.5%)
    produces qty such that qty * close <= 700_000 * 0.005."""
    cfg = _build_cfg(cfg_with_paths, with_tiers=True)
    state = strategy_module.blank_state()
    candidates = [_build_candidate(strategy_module, "MID", 700_000.0)]
    selected = strategy_module.select_entries(
        candidates, state,
        equity=1_000_000.0,    # 10% × $1M = $100k naive target
        latest_prices={},
        cfg=cfg, kill_state=strategy_module.KillLevel.NONE,
    )
    assert len(selected) == 1
    entry = selected[0]
    cap_dollars = 700_000.0 * 0.005   # $3,500
    notional = entry.qty * entry.close_price
    assert notional <= cap_dollars + 1e-6
    # Tighter check: qty is exactly floor(cap/close)
    assert entry.qty == int(cap_dollars // entry.close_price)


def test_select_entries_caps_at_top_tier_1_5_percent(
    strategy_module, cfg_with_paths,
):
    """A $10M ADV candidate (lands in the null/catch-all tier at
    1.5%) produces qty such that qty * close <= 10_000_000 * 0.015."""
    cfg = _build_cfg(cfg_with_paths, with_tiers=True)
    state = strategy_module.blank_state()
    candidates = [_build_candidate(strategy_module, "LIQ", 10_000_000.0)]
    selected = strategy_module.select_entries(
        candidates, state,
        equity=1_000_000.0,
        latest_prices={},
        cfg=cfg, kill_state=strategy_module.KillLevel.NONE,
    )
    assert len(selected) == 1
    entry = selected[0]
    cap_dollars = 10_000_000.0 * 0.015   # $150,000
    notional = entry.qty * entry.close_price
    assert notional <= cap_dollars + 1e-6


def test_select_entries_three_tiers_in_one_slate(
    strategy_module, cfg_with_paths,
):
    """A 3-candidate slate spanning reject / mid / liquid tiers
    produces exactly two entries (the THIN one drops out)."""
    cfg = _build_cfg(cfg_with_paths, with_tiers=True)
    state = strategy_module.blank_state()
    candidates = [
        _build_candidate(strategy_module, "THIN", 200_000.0),
        _build_candidate(strategy_module, "MID", 700_000.0),
        _build_candidate(strategy_module, "LIQ", 10_000_000.0),
    ]
    selected = strategy_module.select_entries(
        candidates, state,
        equity=1_000_000.0, latest_prices={},
        cfg=cfg, kill_state=strategy_module.KillLevel.NONE,
    )
    tickers = sorted(e.ticker for e in selected)
    assert tickers == ["LIQ", "MID"]
    by_ticker = {e.ticker: e for e in selected}
    # MID capped at 0.5% of ADV.
    assert by_ticker["MID"].qty * by_ticker["MID"].close_price <= 700_000 * 0.005 + 1e-6
    # LIQ capped at 1.5% of ADV.
    assert by_ticker["LIQ"].qty * by_ticker["LIQ"].close_price <= 10_000_000 * 0.015 + 1e-6


# ---------------------------------------------------------------- back-compat integration


def test_select_entries_legacy_flat_cap_when_tiers_absent(
    strategy_module, cfg_with_paths,
):
    """With ``adv_tier_caps`` removed from cfg, the legacy
    ``max_position_as_adv_frac: 0.03`` cap is in effect:
      * The THIN ($200k) candidate is NOT rejected — it's capped at
        $200k × 0.03 = $6,000.
      * MID ($700k) capped at $21,000.
      * LIQ ($10M) capped at $300,000.
    """
    cfg = _build_cfg(cfg_with_paths, with_tiers=False)
    state = strategy_module.blank_state()
    candidates = [
        _build_candidate(strategy_module, "THIN", 200_000.0),
        _build_candidate(strategy_module, "MID", 700_000.0),
        _build_candidate(strategy_module, "LIQ", 10_000_000.0),
    ]
    selected = strategy_module.select_entries(
        candidates, state,
        equity=1_000_000.0, latest_prices={},
        cfg=cfg, kill_state=strategy_module.KillLevel.NONE,
    )
    tickers = sorted(e.ticker for e in selected)
    # Critical assertion: THIN is admitted under the legacy path.
    assert tickers == ["LIQ", "MID", "THIN"]
    by_ticker = {e.ticker: e for e in selected}
    assert by_ticker["THIN"].qty * by_ticker["THIN"].close_price <= 200_000 * 0.03 + 1e-6
    assert by_ticker["MID"].qty * by_ticker["MID"].close_price <= 700_000 * 0.03 + 1e-6
    assert by_ticker["LIQ"].qty * by_ticker["LIQ"].close_price <= 10_000_000 * 0.03 + 1e-6


def test_select_entries_unknown_adv_is_rejected_even_with_legacy_cap(
    strategy_module, cfg_with_paths,
):
    """A candidate whose features carry no ``avg_dollar_volume``
    can't be sized against unknown liquidity — adv_tier_cap returns
    ``(False, 0.0)`` and the candidate is dropped."""
    cfg = _build_cfg(cfg_with_paths, with_tiers=False)
    state = strategy_module.blank_state()
    # Candidate with empty features dict — no avg_dollar_volume key.
    cand = strategy_module.Candidate(
        ticker="UNK", close=10.0, signal_strength=5.0,
        venue_code="XNAS", features={},
    )
    selected = strategy_module.select_entries(
        [cand], state, equity=100_000.0, latest_prices={},
        cfg=cfg, kill_state=strategy_module.KillLevel.NONE,
    )
    assert selected == []
