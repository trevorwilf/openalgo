"""Fix Phase 7 — risk & config integrity.

Covers:
- ledger-read guard: unreadable/missing ledgers never zero the
  compounding cumulative,
- ``max_current_return_gate`` wired LIVE in apply_v2_gates,
- ``protected_position.block_entries_on_violation`` wired via the
  ``protection_violation_active`` state flag,
- MTM shadow telemetry (``shadow_max_unrealized_loss``) + the shadow
  ADV tier blocker,
- canonical-reason additions + the qty≤0 relabel to
  ``sizing_zero_qty``,
- dead config keys now REJECTED by the strict schema; the live yaml
  validates clean.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import pytest
import yaml

import bowaka_v2_config_schema as config_schema
import bowaka_v2_features as features
import bowaka_v2_schemas as schemas
import bowaka_v2_strategy as v2

_REPO_ROOT = Path(__file__).resolve().parents[2]
_LIVE_YAML = _REPO_ROOT / "strategies" / "scripts" / "bowaka_v2_config.yaml"


@pytest.fixture(autouse=True)
def _redirect_v2_paths(tmp_path, monkeypatch):
    import bowaka_v2_paths as p
    monkeypatch.setattr(p, "PROTECTION_EVENTS_PATH",
                         tmp_path / "protection_events.jsonl")
    monkeypatch.setattr(p, "V2_LEDGER_PATH",
                         tmp_path / "trade_ledger.jsonl")
    monkeypatch.setattr(p, "V2_DAILY_SUMMARY_PATH",
                         tmp_path / "daily_summary.jsonl")
    monkeypatch.setattr(p, "REJECTED_CANDIDATES_PATH",
                         tmp_path / "rejected_candidates.jsonl")
    monkeypatch.setattr(p, "ENTRY_DECISIONS_PATH",
                         tmp_path / "entry_decisions.jsonl")


# ---- ledger guard ---------------------------------------------------------------


def _ledger_cfg(tmp_path):
    return {"paths": {
        "daily_summary_path": str(tmp_path / "daily_summary.jsonl"),
        "trade_ledger_path": str(tmp_path / "trade_ledger.jsonl"),
    }}


def test_unreadable_ledger_keeps_in_state_cumulative(tmp_path, monkeypatch):
    cfg = _ledger_cfg(tmp_path)
    (tmp_path / "daily_summary.jsonl").write_text(
        json.dumps({"record_type": "closure", "realized_pnl": 100.0})
        + "\n", encoding="utf-8",
    )

    def boom(self, *a, **kw):
        raise OSError("disk error")

    monkeypatch.setattr(Path, "read_text", boom)
    state = {"cumulative_realized_pnl_strategy": -1234.5}
    v2._reconcile_cumulative_from_ledger(state, cfg)
    assert state["cumulative_realized_pnl_strategy"] == -1234.5


def test_missing_ledger_with_nonzero_state_keeps_state(tmp_path):
    cfg = _ledger_cfg(tmp_path)  # no file written
    state = {"cumulative_realized_pnl_strategy": -1234.5}
    v2._reconcile_cumulative_from_ledger(state, cfg)
    assert state["cumulative_realized_pnl_strategy"] == -1234.5


def test_missing_ledger_with_zero_state_seeds_zero(tmp_path):
    cfg = _ledger_cfg(tmp_path)
    state: dict = {}
    v2._reconcile_cumulative_from_ledger(state, cfg)
    assert state["cumulative_realized_pnl_strategy"] == 0.0


def test_readable_ledger_still_overwrites(tmp_path):
    cfg = _ledger_cfg(tmp_path)
    (tmp_path / "daily_summary.jsonl").write_text(
        json.dumps({"record_type": "closure", "realized_pnl": 100.0})
        + "\n"
        + json.dumps({"record_type": "closure", "realized_pnl": -40.0})
        + "\n", encoding="utf-8",
    )
    state = {"cumulative_realized_pnl_strategy": 999.0}
    v2._reconcile_cumulative_from_ledger(state, cfg)
    assert state["cumulative_realized_pnl_strategy"] == pytest.approx(60.0)


# ---- max_current_return_gate ------------------------------------------------------


def _gate(feats, signals):
    _all, gates = features.apply_v2_gates(
        feats, signals, price=5.0, avg_dollar_volume_20d=1_000_000,
        prior_atr_pct=0.08, ema_slope_prior=0.02,
        instrument_class="operating_equity",
    )
    return gates


def test_max_current_return_gate_blocks_above_threshold():
    gates = _gate({"current_return_pct": 0.90},
                  {"current_return_pct_max": 0.68})
    assert gates["max_current_return_gate"] is False


def test_max_current_return_gate_passes_below_threshold():
    gates = _gate({"current_return_pct": 0.20},
                  {"current_return_pct_max": 0.68})
    assert gates["max_current_return_gate"] is True


def test_max_current_return_gate_disabled_by_null_threshold():
    gates = _gate({"current_return_pct": 5.0},
                  {"current_return_pct_max": None})
    assert gates["max_current_return_gate"] is True


def test_max_current_return_gate_none_value_fails_open():
    # Max gates fail open on a missing value (consistent with _le).
    gates = _gate({}, {"current_return_pct_max": 0.68})
    assert gates["max_current_return_gate"] is True


# ---- protection_violation gate -----------------------------------------------------


def _risk_cfg():
    return {
        "protected_position": {"enabled": True,
                                "block_entries_on_violation": True},
        "sizing": {"max_concurrent_positions": 18,
                    "bankroll_fixed_dollars": 90000},
        "risk": {},
    }


def test_protection_violation_blocks_entries_when_flag_set():
    cfg = _risk_cfg()
    state = {"protection_violation_active": True, "open_positions": {}}
    assert v2._risk_gates(
        {"symbol": "AAA"}, state, cfg,
        candidate_adv=None, target_notional=100.0,
    ) == "protection_violation"


def test_protection_violation_clears_when_flag_off():
    cfg = _risk_cfg()
    state = {"protection_violation_active": False, "open_positions": {}}
    assert v2._risk_gates(
        {"symbol": "AAA"}, state, cfg,
        candidate_adv=None, target_notional=100.0,
    ) is None


def test_invariant_pass_sets_and_clears_the_flag(tmp_path):
    cfg = {
        "paths": {
            "trade_ledger_path": str(tmp_path / "trade_ledger.jsonl"),
            "daily_summary_path": str(tmp_path / "daily_summary.jsonl"),
        },
        "execution": {"default_venue_code": "XNAS"},
        "exits": {"stop_pct": 0.05, "target_pct": 0.10},
        "protected_position": {"enabled": True,
                                "max_unprotected_seconds": 5,
                                "flatten_if_unprotected": False,
                                "block_entries_on_violation": True},
        "logging": {"log_protection_state": True},
    }
    # A filled lot with no bracket, aged past max_unprotected_seconds.
    state = {"open_positions": {"L-1": {
        "symbol": "AAA", "qty": 100, "status": "filled",
        "link_id": "L-1", "entry_price": 10.0,
        "entry_timestamp": "2026-07-10T14:00:00Z",
        "parent_fill_processed_at": "2026-07-10T14:00:00Z",
        "child_order_ids": {"target": "", "stop": ""},
    }}}

    class OA:
        pass

    v2.enforce_protected_position_invariant_v2(
        state, cfg, oa_client=OA(), api_key="k", http=None,
    )
    assert state["protection_violation_active"] is True
    # Bracket restored → the next pass clears the flag.
    state["open_positions"]["L-1"]["child_order_ids"] = {
        "target": "T-1", "stop": "S-1",
    }
    v2.enforce_protected_position_invariant_v2(
        state, cfg, oa_client=OA(), api_key="k", http=None,
    )
    assert state["protection_violation_active"] is False


# ---- MTM shadow + shadow ADV --------------------------------------------------------


def _shadow_cfg(**shadow):
    return {
        "sizing": {"bankroll_fixed_dollars": 90000},
        "risk": {"shadow": shadow},
    }


def test_shadow_max_unrealized_loss_fires_on_estimate():
    cfg = _shadow_cfg(max_unrealized_loss_pct=0.04)
    state = {
        "daily_realized_pnl_strategy": -1000.0,
        "unrealized_pnl_estimate": {"value": -3000.0,
                                     "ts": "2026-07-14T15:00:00Z"},
        "open_positions": {},
    }
    # (-1000 + -3000) / 90000 = -4.44% <= -4%
    blockers = v2._shadow_risk_check(
        {"symbol": "AAA"}, state, cfg,
        candidate_adv=None, target_notional=100.0,
    )
    assert "shadow_max_unrealized_loss" in blockers
    # Positive unrealized never offsets realized losses (min(0, u)).
    state["unrealized_pnl_estimate"]["value"] = 500.0
    blockers = v2._shadow_risk_check(
        {"symbol": "AAA"}, state, cfg,
        candidate_adv=None, target_notional=100.0,
    )
    assert "shadow_max_unrealized_loss" not in blockers


def test_shadow_mtm_silent_without_estimate():
    cfg = _shadow_cfg(max_unrealized_loss_pct=0.04)
    state = {"daily_realized_pnl_strategy": -80000.0,
             "open_positions": {}}
    blockers = v2._shadow_risk_check(
        {"symbol": "AAA"}, state, cfg,
        candidate_adv=None, target_notional=100.0,
    )
    assert "shadow_max_unrealized_loss" not in blockers


def test_shadow_adv_tier_blocker_fires():
    cfg = _shadow_cfg(adv_tier_caps=[
        {"max_adv_dollars": 250000, "reject_if_below": True},
        {"max_adv_dollars": None, "max_position_as_adv_frac": 0.002},
    ])
    state = {"open_positions": {}}
    # ADV 1M → shadow cap = 2000; target 5000 exceeds it.
    blockers = v2._shadow_risk_check(
        {"symbol": "AAA"}, state, cfg,
        candidate_adv=1_000_000, target_notional=5000.0,
    )
    assert "shadow_adv_cap" in blockers
    # Under the cap → silent.
    blockers = v2._shadow_risk_check(
        {"symbol": "AAA"}, state, cfg,
        candidate_adv=1_000_000, target_notional=1500.0,
    )
    assert "shadow_adv_cap" not in blockers


def test_compute_unrealized_pnl_sums_marks_and_skips_bad_quotes():
    state = {"open_positions": {
        "L-1": {"symbol": "AAA", "status": "filled",
                 "entry_price": 10.0, "qty": 100},
        "L-2": {"symbol": "BBB", "status": "filled",
                 "entry_price": 5.0, "qty": 200},
        "L-3": {"symbol": "CCC", "status": "pending_fill",
                 "entry_price": 2.0, "qty": 50},
    }}
    quotes = {
        "AAA": {"mid": 11.0},
        "BBB": None,               # no quote → skipped
    }
    est = v2.compute_unrealized_pnl(state, lambda s: quotes.get(s))
    assert est == pytest.approx((11.0 - 10.0) * 100)
    assert v2.compute_unrealized_pnl(state, None) is None
    assert v2.compute_unrealized_pnl({"open_positions": {}},
                                      lambda s: None) is None


# ---- canonical reasons + relabel ------------------------------------------------------


def test_new_canonical_reasons_present():
    for reason in ("bankroll_floor_halt", "max_lots_per_symbol",
                    "sizing_zero_qty", "protection_violation",
                    "unresolved_order_outcome"):
        assert reason in schemas.CANONICAL_REJECTION_REASONS


def test_zero_qty_rejection_relabelled(tmp_path):
    """A candidate whose price exceeds the whole sizing slice must be
    rejected sizing_zero_qty, not adv_cap."""
    import copy
    cand = {
        "schema_version": schemas.CANDIDATE_EVENT_SCHEMA_VERSION,
        "strategy": "bowaka_v2", "event_type": "candidate_signal",
        "event_id": "e-1", "generated_at": "2026-05-18T14:35:00Z",
        "session_date": "2026-05-18",
        "scan_timestamp": "2026-05-18T14:35:00Z",
        "provider": "alpaca", "data_feed": "iex", "bar_interval": "1m",
        "config_hash": "sha256:t", "universe_hash": "sha256:t",
        "symbol": "AAA", "exchange": "NASDAQ", "venue_code": "XNAS",
        "instrument_class": "operating_equity",
        "eligible_for_bowaka_equity_bucket": True,
        "prior_daily_baselines": {
            "prior_close": 7.42, "avg_volume_20d": 450000,
            "avg_dollar_volume_20d": 3_000_000,
            "prior_atr_14d": 0.52, "prior_atr_pct": 0.0701,
            "ema_10_prior": 7.18, "ema_10_lag_3": 7.04,
            "ema_slope_prior": 0.0199,
        },
        "forming_session_bar": {
            "session_open": 7.61, "session_high": 8.20,
            "session_low": 7.50,
            "last_price": 99999.0,        # price >> slice ⇒ qty 0
            "session_volume": 820000, "session_range": 0.70,
            "last_bar_timestamp": "2026-05-18T18:34:00Z",
        },
        "intraday_volume_context": {
            "volume_curve_fraction": 0.42,
            "expected_volume_until_scan": 189000,
            "rvol_so_far": 4.34, "projected_full_day_rvol": 4.34,
        },
        "features": {"gap_pct": 0.02, "current_return_pct": 0.14,
                      "range_expansion_so_far": 1.3,
                      "close_location_so_far": 0.87,
                      "ema_distance": 0.12, "ema_slope": 0.0199,
                      "signal_strength": 7.82},
        "gate_results": {
            "price_gate": True, "avg_dollar_volume_gate": True,
            "rvol_gate": True, "prior_atr_pct_gate": True,
            "range_expansion_gate": True, "close_location_gate": True,
            "ema_distance_gate": True, "ema_slope_gate": True,
            "max_gap_gate": True, "instrument_gate": True,
        },
        "candidate_rank": 1,
        "signal_expiry_timestamp": "2026-05-19T00:00:00Z",
    }
    cand = copy.deepcopy(cand)
    cand_path = tmp_path / "candidates.jsonl"
    cand_path.write_text(json.dumps(cand) + "\n", encoding="utf-8")
    cfg = {
        "strategy": {"mode": "forming_daily_bar_monitor",
                       "environment": "paper"},
        "paths": {"candidate_events_path": str(cand_path),
                    "trade_ledger_path": str(tmp_path / "l.jsonl"),
                    "daily_summary_path": str(tmp_path / "d.jsonl")},
        "data": {"feed": "iex", "allow_non_sip_for_research_only": True},
        "execution": {"default_venue_code": "XNAS",
                        "quote_gate": {"enabled": False},
                        "price_chase_gate": {"enabled": False},
                        "halt_gate": {"enabled": False}},
        "sizing": {"bankroll_fixed_dollars": 90000,
                     "max_concurrent_positions": 18,
                     "equal_slice_bankroll_fraction": 0.80,
                     "min_order_notional": 500},
        "risk": {},
        "exits": {"stop_pct": 0.08, "target_pct": 0.15,
                    "max_hold_days": 3},
        "logging": {"emit_entry_decisions": False,
                       "emit_rejected_candidates": True},
    }
    state = {"last_consumed_event_offset": 0, "entered_today": [],
             "daily_entries_count": 0, "open_positions": {}}
    s = v2.consume_candidate_events(
        state, cfg,
        submit_supplier=lambda sym, qty: pytest.fail("must not submit"),
        today_iso="2026-05-18",
        now_utc=datetime(2026, 5, 18, 18, 35, tzinfo=timezone.utc),
    )
    assert s["rejected"] == 1
    rejected = [json.loads(line) for line in
                (tmp_path / "rejected_candidates.jsonl")
                .read_text(encoding="utf-8").splitlines()]
    assert rejected[0]["reason"] == "sizing_zero_qty"


# ---- config schema + yaml ----------------------------------------------------------


@pytest.mark.parametrize("dead_key_doc", [
    {"scanner": {"full_universe_refresh_interval_minutes": 5}},
    {"scanner": {"in_play_refresh_interval_seconds": 60}},
    {"scanner": {"require_prior_daily_baseline": True}},
    {"logging": {"emit_candidate_events": True}},
    {"logging": {"intraday_tick_interval_seconds": 60}},
    {"logging": {"file": "logs/x.log"}},
    {"paths": {"log_path": "logs/x.log"}},
    {"data": {"max_quote_age_seconds": 15}},
])
def test_removed_dead_keys_now_rejected(dead_key_doc, monkeypatch):
    monkeypatch.delenv("BOWAKA_CONFIG_ALLOW_UNKNOWN", raising=False)
    with pytest.raises(config_schema.ConfigError):
        config_schema.validate_config(dead_key_doc)


def test_kept_live_fallback_key_still_valid():
    config_schema.validate_config(
        {"risk": {"max_position_as_adv_frac": 0.01}},
    )


def test_live_yaml_validates_clean_and_has_shadow_mtm():
    cfg = yaml.safe_load(_LIVE_YAML.read_text(encoding="utf-8"))
    config_schema.validate_config(cfg)   # must not raise
    assert cfg["risk"]["shadow"]["max_unrealized_loss_pct"] == 0.04
    # The dead keys are actually gone from the shipped yaml.
    assert "log_path" not in cfg["paths"]
    assert "max_quote_age_seconds" not in cfg["data"]
    assert "file" not in cfg["logging"]
    assert "emit_candidate_events" not in cfg["logging"]
    assert "full_universe_refresh_interval_minutes" not in cfg["scanner"]
