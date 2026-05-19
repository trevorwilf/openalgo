"""Phase 5 — paper-mode YAML profile + shadow controls.

Covers:
* YAML profile: risk.daily_loss_pct is None,
  risk.max_gross_exposure_pct == 2.00,
  sizing.equal_slice_bankroll_fraction == 0.80.
* Per-trade dollars unchanged at $4,000 despite the gross-cap
  relaxation (sizing pinned by equal_slice_bankroll_fraction).
* compute_shadow_controls correctly computes the would-block
  conditions.
* daily_loss_pct=null does NOT crash update_daily_pnl.
* entry_decision events carry the shadow_controls payload.
"""
from __future__ import annotations

import copy
import json
from pathlib import Path

import httpx
import pytest
import yaml

import bowaka_strategy as bw


_REPO_YAML = (
    Path(__file__).resolve().parents[2]
    / "strategies" / "scripts" / "bowaka_strategy.yaml"
)


# ---- YAML profile ----------------------------------------------------


def test_yaml_paper_profile_relaxed_caps() -> None:
    cfg = yaml.safe_load(_REPO_YAML.read_text())
    assert cfg["risk"]["daily_loss_pct"] is None
    assert cfg["risk"]["max_gross_exposure_pct"] == 2.00
    assert cfg["risk"]["max_total_entries_per_day"] == 25
    assert cfg["risk"]["max_stopouts_per_day"] is None
    assert cfg["risk"]["stop_trading_after_consecutive_stopouts"] is None
    assert cfg["sizing"]["equal_slice_bankroll_fraction"] == 0.80
    assert cfg["sizing"]["max_concurrent_positions"] == 18
    assert cfg["exits"]["protected_position"]["block_entries_on_violation"] is False
    assert cfg["logging"]["log_candidate_decisions"] is True
    assert cfg["logging"]["log_shadow_risk_controls"] is True


def test_per_trade_dollars_unchanged_after_gross_cap_relaxation() -> None:
    """The audit's §6.2 nuance: relaxing max_gross_exposure_pct from
    0.80 to 2.00 must NOT auto-scale per-trade dollars. The
    equal_slice_bankroll_fraction=0.80 pin reproduces the $4,000
    behavior."""
    cfg = yaml.safe_load(_REPO_YAML.read_text())
    bankroll = 90_000.0
    max_concurrent = int(cfg["sizing"]["max_concurrent_positions"])
    frac = float(cfg["sizing"]["equal_slice_bankroll_fraction"])
    per_trade_dollars = frac * bankroll / max_concurrent
    assert per_trade_dollars == pytest.approx(4000.0)


# ---- compute_shadow_controls ----------------------------------------


def _state_with_bankroll(bk: float = 90_000.0,
                          pnl_today: float = 0.0,
                          consec_stopouts: int = 0) -> bw.State:
    state = bw.blank_state()
    state["bankroll"] = {"current_dollars": bk}
    state["daily_realized_pnl_strategy"] = pnl_today
    state["consecutive_stopouts_count"] = consec_stopouts
    return state


def test_shadow_would_block_daily_loss_1pct_when_pnl_negative() -> None:
    state = _state_with_bankroll(pnl_today=-1_800.0)  # -2% of 90k
    out = bw.compute_shadow_controls(
        state, {},
        candidate_notional=4_000.0,
        is_stopout_day=False,
        current_gross_exposure_dollars=10_000.0,
        entries_today=3,
    )
    assert out["would_block_daily_loss_1pct"] is True
    assert out["would_block_daily_loss_3pct"] is False


def test_shadow_would_block_gross_exposure_40pct() -> None:
    state = _state_with_bankroll(bk=90_000.0)
    # gross exposure post-add = 50k -> 55.5% > 40%.
    out = bw.compute_shadow_controls(
        state, {},
        candidate_notional=4_000.0,
        is_stopout_day=False,
        current_gross_exposure_dollars=46_000.0,
        entries_today=3,
    )
    assert out["would_block_gross_exposure_40pct"] is True


def test_shadow_max_entries_thresholds() -> None:
    state = _state_with_bankroll()
    out = bw.compute_shadow_controls(
        state, {},
        candidate_notional=4_000.0,
        is_stopout_day=False,
        current_gross_exposure_dollars=0.0,
        entries_today=5,
    )
    assert out["would_block_max_entries_4"] is True
    assert out["would_block_max_entries_10"] is False


def test_shadow_consecutive_stopouts() -> None:
    state = _state_with_bankroll(consec_stopouts=2)
    out = bw.compute_shadow_controls(
        state, {},
        candidate_notional=4_000.0,
        is_stopout_day=False,
        current_gross_exposure_dollars=0.0,
        entries_today=0,
    )
    assert out["would_block_after_2_stopouts"] is True


# ---- update_daily_pnl handles null threshold -------------------------


def test_update_daily_pnl_null_threshold_does_not_trip(
    cfg_with_paths, tmp_path,
):
    cfg = copy.deepcopy(cfg_with_paths)
    cfg["risk"]["daily_loss_pct"] = None  # paper-mode profile
    state = bw.blank_state()
    state["daily_pnl_baseline_equity"] = 100_000.0
    state_path = Path(cfg["paths"]["state_path"])
    bw.save_state(state, state_path)
    # Deep drawdown — would trip under the legacy threshold.
    tripped = bw.update_daily_pnl(state, 90_000.0, cfg, state_path=state_path)
    assert tripped is False
    assert state["daily_pnl_tripped"] is False


# ---- entry_decision events carry shadow_controls --------------------


def test_rejected_decision_event_carries_shadow_controls(
    cfg_with_paths, tmp_path,
):
    cfg = copy.deepcopy(cfg_with_paths)
    state = bw.blank_state()
    state["bankroll"] = {"current_dollars": 90_000.0}
    state["consecutive_stopouts_count"] = 3
    # Use an already-held ticker so select_entries rejects on
    # already_held — a deterministic rejection path.
    state["open_positions"] = {"X": {"status": "filled"}}
    cand = bw.Candidate(
        "X", close=10.0, signal_strength=5.0,
        venue_code="XNAS",
        features={"avg_dollar_volume": 1e7},
    )
    selected = bw.select_entries(
        [cand], state, equity=90_000.0, latest_prices={},
        cfg=cfg, kill_state=bw.KillLevel.NONE,
    )
    assert selected == []
    ledger = bw._ledger_path(cfg)
    events = [
        json.loads(l) for l in ledger.read_text().splitlines() if l.strip()
    ]
    decisions = [e for e in events if e["event_type"] == "entry_decision"]
    assert len(decisions) >= 1
    payload = decisions[0]["payload"]
    sh = payload.get("shadow_controls")
    assert sh is not None
    assert sh["would_block_after_2_stopouts"] is True
    assert "would_block_daily_loss_1pct" in sh
    assert "would_block_max_entries_10" in sh
    assert sh["paper_mode_hard_block_applied"] is False
