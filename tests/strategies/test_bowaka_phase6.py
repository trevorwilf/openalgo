"""Phase 6 — Bankroll envelope.

The strategy's working capital is a strategy-specific value (the
"bankroll"), seeded from cfg and grown / shrunk by realized P&L of
bowaka's own closures. All sizing decisions read this number, NOT the
full account equity, so the operator can keep bowaka isolated to a
defined subset of the account.

Covers:
- Init with ``fixed_dollars`` (no broker call needed).
- Init with ``pct_of_cash`` (broker /balances call).
- Init clamped to ``cap_dollars`` when initial exceeds cap.
- Cfg validation: both pct_of_cash and fixed_dollars set → error.
- Cfg validation: neither set → error.
- Cfg validation: pct_of_cash out of (0, 1] → error.
- Cfg validation: non-numeric / non-positive → error.
- ``reset_token`` change re-seeds; unchanged → no-op.
- ``apply_realized_pnl_to_bankroll``: gain, loss, cap, clamp-at-zero,
  high_water_mark monotonic.
- ``get_sizing_basis``: returns bankroll when present, fallback otherwise.
- Closing a position propagates realized P&L into the bankroll.
- ``reset_for_new_session`` preserves the bankroll (it's not a daily
  thing — only the reset_token can change it).
- State survives "reboot" (load_state reads the persisted dict).
- BankrollConfigError surfaces at run_loop startup (refuse to start).
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import httpx
import pytest


# ---------------------------------------------------------------- helpers


def _route(handlers):
    def handler(req: httpx.Request) -> httpx.Response:
        key = (req.method, req.url.path)
        h = handlers.get(key)
        if h is None:
            return httpx.Response(404, json={"error": {"code": "no_route"}})
        return h(req) if callable(h) else h
    return httpx.MockTransport(handler)


def _balances(cash, equity=None):
    eq = equity if equity is not None else cash
    def h(req):
        return httpx.Response(200, json={"data": {"balance": {
            "cash": str(cash), "equity": str(eq),
            "buying_power": str(cash * 2), "currency": "USD",
        }}})
    return h


def _cfg(initial, cap=None, token=""):
    """Build a minimal cfg with a bankroll block (and the other keys
    apply_realized_pnl might read)."""
    return {
        "bankroll": {
            "initial": initial,
            "cap_dollars": cap,
            "reset_token": token,
        },
    }


# ---------------------------------------------------------------- cfg validation


def test_bankroll_validate_both_set_raises(strategy_module):
    with pytest.raises(strategy_module.BankrollConfigError, match="set EXACTLY one"):
        strategy_module._validate_bankroll_cfg({
            "initial": {"pct_of_cash": 0.10, "fixed_dollars": 10000},
        })


def test_bankroll_validate_neither_set_raises(strategy_module):
    with pytest.raises(strategy_module.BankrollConfigError, match="exactly one"):
        strategy_module._validate_bankroll_cfg({
            "initial": {"pct_of_cash": None, "fixed_dollars": None},
        })


def test_bankroll_validate_pct_out_of_range_raises(strategy_module):
    with pytest.raises(strategy_module.BankrollConfigError, match=r"in \(0, 1\]"):
        strategy_module._validate_bankroll_cfg({
            "initial": {"pct_of_cash": 1.5, "fixed_dollars": None},
        })


def test_bankroll_validate_pct_zero_raises(strategy_module):
    with pytest.raises(strategy_module.BankrollConfigError):
        strategy_module._validate_bankroll_cfg({
            "initial": {"pct_of_cash": 0.0, "fixed_dollars": None},
        })


def test_bankroll_validate_fixed_negative_raises(strategy_module):
    with pytest.raises(strategy_module.BankrollConfigError, match=r"> 0"):
        strategy_module._validate_bankroll_cfg({
            "initial": {"pct_of_cash": None, "fixed_dollars": -100},
        })


def test_bankroll_validate_cap_non_positive_raises(strategy_module):
    with pytest.raises(strategy_module.BankrollConfigError, match=r"> 0"):
        strategy_module._validate_bankroll_cfg({
            "initial": {"pct_of_cash": None, "fixed_dollars": 1000},
            "cap_dollars": 0,
        })


def test_bankroll_validate_valid_passes(strategy_module):
    # No assertion needed; success = no exception.
    strategy_module._validate_bankroll_cfg({
        "initial": {"pct_of_cash": None, "fixed_dollars": 10000},
        "cap_dollars": 300000,
    })


# ---------------------------------------------------------------- init


def test_bankroll_init_fixed_dollars(strategy_module, cfg_with_paths):
    state = strategy_module.blank_state()
    state_path = Path(cfg_with_paths["paths"]["state_path"])
    cfg = dict(cfg_with_paths)
    cfg.update(_cfg(initial={"pct_of_cash": None, "fixed_dollars": 10000},
                    cap=300000))
    # No HTTP calls expected for fixed_dollars mode.
    http = strategy_module.make_http_client("http://x", transport=_route({}))
    did = strategy_module.initialize_bankroll(
        state, cfg, http, "k", state_path=state_path,
    )
    assert did is True
    bk = state["bankroll"]
    assert bk["current_dollars"] == 10000.0
    assert bk["high_water_mark"] == 10000.0
    assert "fixed_dollars=10000" in bk["initial_source"]
    assert bk["last_reset_token"] == ""


def test_bankroll_init_pct_of_cash(strategy_module, cfg_with_paths):
    state = strategy_module.blank_state()
    state_path = Path(cfg_with_paths["paths"]["state_path"])
    cfg = dict(cfg_with_paths)
    cfg.update(_cfg(initial={"pct_of_cash": 0.10, "fixed_dollars": None}))
    http = strategy_module.make_http_client("http://x", transport=_route({
        ("GET", "/api/v2/balances"): _balances(cash=50_000.0),
    }))
    did = strategy_module.initialize_bankroll(
        state, cfg, http, "k", state_path=state_path,
    )
    assert did is True
    assert state["bankroll"]["current_dollars"] == 5000.0
    assert "pct_of_cash=0.1" in state["bankroll"]["initial_source"]


def test_bankroll_init_initial_clamped_to_cap(strategy_module, cfg_with_paths):
    """Operator sets initial=50k but cap=10k → clamps to 10k and notes
    the clamp in initial_source for transparency."""
    state = strategy_module.blank_state()
    state_path = Path(cfg_with_paths["paths"]["state_path"])
    cfg = dict(cfg_with_paths)
    cfg.update(_cfg(initial={"pct_of_cash": None, "fixed_dollars": 50000},
                    cap=10000))
    http = strategy_module.make_http_client("http://x", transport=_route({}))
    strategy_module.initialize_bankroll(
        state, cfg, http, "k", state_path=state_path,
    )
    assert state["bankroll"]["current_dollars"] == 10000.0
    assert "clamped to cap=10000" in state["bankroll"]["initial_source"]


def test_bankroll_init_no_feature_no_state(strategy_module, cfg_with_paths):
    """Operator omits the cfg.bankroll block entirely → no state
    written. Sizing falls back to broker equity. Pre-bankroll
    operators see no behavior change."""
    state = strategy_module.blank_state()
    state_path = Path(cfg_with_paths["paths"]["state_path"])
    http = strategy_module.make_http_client("http://x", transport=_route({}))
    did = strategy_module.initialize_bankroll(
        state, cfg_with_paths, http, "k", state_path=state_path,
    )
    assert did is False
    assert "bankroll" not in state or not state["bankroll"]


def test_bankroll_init_idempotent_with_same_token(strategy_module, cfg_with_paths):
    state = strategy_module.blank_state()
    state_path = Path(cfg_with_paths["paths"]["state_path"])
    cfg = dict(cfg_with_paths)
    cfg.update(_cfg(initial={"pct_of_cash": None, "fixed_dollars": 10000},
                    token="alpha"))
    http = strategy_module.make_http_client("http://x", transport=_route({}))
    # First init.
    strategy_module.initialize_bankroll(
        state, cfg, http, "k", state_path=state_path,
    )
    # Simulate some P&L drift.
    state["bankroll"]["current_dollars"] = 12345.67
    # Second call with the SAME token must NOT re-seed.
    did = strategy_module.initialize_bankroll(
        state, cfg, http, "k", state_path=state_path,
    )
    assert did is False
    assert state["bankroll"]["current_dollars"] == 12345.67  # untouched


def test_bankroll_reset_token_change_reseeds(strategy_module, cfg_with_paths):
    state = strategy_module.blank_state()
    state_path = Path(cfg_with_paths["paths"]["state_path"])
    cfg = dict(cfg_with_paths)
    cfg.update(_cfg(initial={"pct_of_cash": None, "fixed_dollars": 10000},
                    token="alpha"))
    http = strategy_module.make_http_client("http://x", transport=_route({}))
    strategy_module.initialize_bankroll(
        state, cfg, http, "k", state_path=state_path,
    )
    state["bankroll"]["current_dollars"] = 50000.0  # imagine growth
    # Operator changes the token → re-seed.
    cfg["bankroll"]["reset_token"] = "beta"
    did = strategy_module.initialize_bankroll(
        state, cfg, http, "k", state_path=state_path,
    )
    assert did is True
    assert state["bankroll"]["current_dollars"] == 10000.0
    assert state["bankroll"]["last_reset_token"] == "beta"


def test_bankroll_init_invalid_cfg_raises(strategy_module, cfg_with_paths):
    state = strategy_module.blank_state()
    state_path = Path(cfg_with_paths["paths"]["state_path"])
    cfg = dict(cfg_with_paths)
    cfg.update(_cfg(initial={"pct_of_cash": None, "fixed_dollars": None}))
    http = strategy_module.make_http_client("http://x", transport=_route({}))
    with pytest.raises(strategy_module.BankrollConfigError):
        strategy_module.initialize_bankroll(
            state, cfg, http, "k", state_path=state_path,
        )


# ---------------------------------------------------------------- apply_realized_pnl


def test_apply_realized_pnl_gain_grows_bankroll(strategy_module):
    state = strategy_module.blank_state()
    state["bankroll"] = {
        "current_dollars": 10000.0, "high_water_mark": 10000.0,
        "initialized_at": "...", "initial_source": "...",
        "last_reset_token": "",
    }
    cfg = _cfg(initial={"pct_of_cash": None, "fixed_dollars": 10000},
               cap=300000)
    strategy_module.apply_realized_pnl_to_bankroll(state, cfg, 500.0)
    assert state["bankroll"]["current_dollars"] == 10500.0
    assert state["bankroll"]["high_water_mark"] == 10500.0


def test_apply_realized_pnl_loss_shrinks_bankroll(strategy_module):
    state = strategy_module.blank_state()
    state["bankroll"] = {
        "current_dollars": 10000.0, "high_water_mark": 10000.0,
        "initialized_at": "...", "initial_source": "...",
        "last_reset_token": "",
    }
    cfg = _cfg(initial={"pct_of_cash": None, "fixed_dollars": 10000})
    strategy_module.apply_realized_pnl_to_bankroll(state, cfg, -1500.0)
    assert state["bankroll"]["current_dollars"] == 8500.0
    # HWM doesn't decrease.
    assert state["bankroll"]["high_water_mark"] == 10000.0


def test_apply_realized_pnl_clamps_at_cap(strategy_module):
    """Profits above the cap are forfeit. Cap = $300k, bankroll = $299k,
    realized = +$5k → bankroll = $300k (not $304k)."""
    state = strategy_module.blank_state()
    state["bankroll"] = {
        "current_dollars": 299_000.0, "high_water_mark": 299_000.0,
        "initialized_at": "...", "initial_source": "...",
        "last_reset_token": "",
    }
    cfg = _cfg(initial={"pct_of_cash": None, "fixed_dollars": 10000},
               cap=300000)
    strategy_module.apply_realized_pnl_to_bankroll(state, cfg, 5000.0)
    assert state["bankroll"]["current_dollars"] == 300000.0


def test_apply_realized_pnl_clamps_at_zero(strategy_module):
    """A massive loss can't drive the bankroll below zero. Bankroll
    = $1000, realized = -$5000 → bankroll = $0 (not -$4000)."""
    state = strategy_module.blank_state()
    state["bankroll"] = {
        "current_dollars": 1000.0, "high_water_mark": 1000.0,
        "initialized_at": "...", "initial_source": "...",
        "last_reset_token": "",
    }
    cfg = _cfg(initial={"pct_of_cash": None, "fixed_dollars": 10000})
    strategy_module.apply_realized_pnl_to_bankroll(state, cfg, -5000.0)
    assert state["bankroll"]["current_dollars"] == 0.0


def test_apply_realized_pnl_no_op_when_disabled(strategy_module):
    """No bankroll dict in state → feature disabled. Function must be
    a silent no-op (legacy operators see no change in behavior)."""
    state = strategy_module.blank_state()
    cfg = _cfg(initial={"pct_of_cash": None, "fixed_dollars": 10000})
    strategy_module.apply_realized_pnl_to_bankroll(state, cfg, 500.0)
    assert "bankroll" not in state or not state.get("bankroll")


def test_apply_realized_pnl_no_cap_unbounded_growth(strategy_module):
    state = strategy_module.blank_state()
    state["bankroll"] = {
        "current_dollars": 1_000_000.0, "high_water_mark": 1_000_000.0,
        "initialized_at": "...", "initial_source": "...",
        "last_reset_token": "",
    }
    cfg = _cfg(initial={"pct_of_cash": None, "fixed_dollars": 10000},
               cap=None)
    strategy_module.apply_realized_pnl_to_bankroll(state, cfg, 500_000.0)
    assert state["bankroll"]["current_dollars"] == 1_500_000.0


# ---------------------------------------------------------------- get_sizing_basis


def test_get_sizing_basis_returns_bankroll_when_set(strategy_module):
    state = strategy_module.blank_state()
    state["bankroll"] = {"current_dollars": 10000.0}
    assert strategy_module.get_sizing_basis(
        state, fallback_equity=999_999.0,
    ) == 10000.0


def test_get_sizing_basis_falls_back_to_equity_when_unset(strategy_module):
    state = strategy_module.blank_state()
    assert strategy_module.get_sizing_basis(
        state, fallback_equity=100_000.0,
    ) == 100_000.0


# ---------------------------------------------------------------- closure integration


def test_close_position_updates_bankroll(strategy_module, cfg_with_paths):
    """Closure path drives realized P&L into the bankroll. This is
    the integration that makes the envelope actually compound."""
    state = strategy_module.blank_state()
    state["bankroll"] = {
        "current_dollars": 10000.0, "high_water_mark": 10000.0,
        "initialized_at": "...", "initial_source": "...",
        "last_reset_token": "",
    }
    state["open_positions"] = {
        "AAPL": {
            "qty": 100, "entry_price": 100.0,
            "entry_timestamp": "2026-05-10T13:30:00+00:00",
            "status": "filled", "venue_code": "XNAS",
            "entry_features": {}, "child_order_ids": {},
        },
    }
    cfg = dict(cfg_with_paths)
    cfg["bankroll"] = {
        "initial": {"pct_of_cash": None, "fixed_dollars": 10000},
        "cap_dollars": 300000, "reset_token": "",
    }
    summary_path = Path(cfg["paths"]["daily_summary_path"])
    state_path = Path(cfg["paths"]["state_path"])
    strategy_module.close_position(
        "AAPL", state, cfg,
        state_path=state_path, summary_path=summary_path,
        exit_price=115.0, reason="target_hit",
    )
    # +$1,500 realized → bankroll +$1,500.
    assert state["bankroll"]["current_dollars"] == 11500.0
    assert state["bankroll"]["high_water_mark"] == 11500.0


def test_close_position_no_bankroll_no_change(
    strategy_module, cfg_with_paths,
):
    """Operator with bankroll disabled — close_position must work
    exactly as before (no bankroll mutation, no errors)."""
    state = strategy_module.blank_state()
    state["open_positions"] = {
        "AAPL": {
            "qty": 100, "entry_price": 100.0,
            "entry_timestamp": "2026-05-10T13:30:00+00:00",
            "status": "filled", "venue_code": "XNAS",
            "entry_features": {}, "child_order_ids": {},
        },
    }
    summary_path = Path(cfg_with_paths["paths"]["daily_summary_path"])
    state_path = Path(cfg_with_paths["paths"]["state_path"])
    rec = strategy_module.close_position(
        "AAPL", state, cfg_with_paths,
        state_path=state_path, summary_path=summary_path,
        exit_price=115.0, reason="target_hit",
    )
    assert rec["realized_pnl"] == pytest.approx(1500.0)
    assert "bankroll" not in state or not state.get("bankroll")


# ---------------------------------------------------------------- state lifecycle


def test_reset_for_new_session_preserves_bankroll(strategy_module):
    """The bankroll is a multi-day cumulative — daily reset must NOT
    touch it. Only the reset_token mechanism may re-seed."""
    state = strategy_module.blank_state()
    state["bankroll"] = {
        "current_dollars": 12345.67, "high_water_mark": 15000.0,
        "initialized_at": "2026-05-01T00:00:00Z",
        "initial_source": "fixed_dollars=10000",
        "last_reset_token": "v1",
    }
    strategy_module.reset_for_new_session(state, "2026-05-12", 99_561.86)
    assert state["bankroll"]["current_dollars"] == 12345.67
    assert state["bankroll"]["high_water_mark"] == 15000.0
    assert state["bankroll"]["last_reset_token"] == "v1"


def test_bankroll_survives_save_load_roundtrip(
    strategy_module, cfg_with_paths, tmp_path,
):
    """Reboot simulation: write state with bankroll, load back, check
    fields intact. This is the property that lets the envelope survive
    a strategy restart."""
    state_path = Path(cfg_with_paths["paths"]["state_path"])
    state = strategy_module.blank_state()
    state["bankroll"] = {
        "current_dollars": 11234.56, "high_water_mark": 12000.0,
        "initialized_at": "2026-05-01T13:30:00+00:00",
        "initial_source": "fixed_dollars=10000",
        "last_reset_token": "alpha",
    }
    strategy_module.save_state(state, state_path)
    loaded = strategy_module.load_state(state_path)
    assert loaded["bankroll"]["current_dollars"] == 11234.56
    assert loaded["bankroll"]["high_water_mark"] == 12000.0
    assert loaded["bankroll"]["last_reset_token"] == "alpha"


# ---------------------------------------------------------------- sizing integration


def test_sizing_basis_uses_bankroll_in_select_entries(
    strategy_module, cfg_with_paths,
):
    """Hand select_entries the bankroll value via the equity arg —
    sizing should compute as `bankroll * per_trade_pct`, NOT the
    fallback equity. We verify by feeding a SMALL bankroll and a
    LARGE equity: only the bankroll figure dictates qty.

    Note: the ADV-tier-caps feature rejects candidates without an
    ``avg_dollar_volume``; stamp a permissive ADV so the bankroll
    arithmetic is what's under test.
    """
    cfg = dict(cfg_with_paths)
    cfg["risk"] = {**cfg_with_paths["risk"], "max_position_as_adv_frac": None}
    cands = [strategy_module.Candidate(
        "AAPL", close=10.0, signal_strength=9.0,
        features={"avg_dollar_volume": 1_000_000_000.0},
    )]
    state = strategy_module.blank_state()
    state["bankroll"] = {"current_dollars": 10_000.0}
    # Sizing basis = 10k * 0.10 = 1k → 100 shares @ $10.
    basis = strategy_module.get_sizing_basis(state, fallback_equity=1_000_000.0)
    assert basis == 10_000.0
    selected = strategy_module.select_entries(
        cands, state, equity=basis, latest_prices={},
        cfg=cfg, kill_state=strategy_module.KillLevel.NONE,
    )
    assert len(selected) == 1
    assert selected[0].qty == 100  # NOT 10_000 (would be 1M*0.10/10)


# ---------------------------------------------------------------- daily_allocation


def _cfg_with_daily_alloc(*, max_hold_days=3, da_days=None, da_enabled=True):
    """Minimal cfg containing exits.max_hold_days + the bankroll
    daily_allocation block."""
    return {
        "exits": {"max_hold_days": max_hold_days},
        "bankroll": {
            "initial": {"pct_of_cash": None, "fixed_dollars": 90000},
            "cap_dollars": 300000,
            "reset_token": "",
            "daily_allocation": {
                "enabled": da_enabled,
                "days": da_days,
            },
        },
    }


def test_get_sizing_basis_slices_by_max_hold_days(strategy_module):
    """The canonical case: bankroll=$90k, max_hold_days=3 → per-day
    sizing basis = $30k. The user can verify this matches their
    intent by running with these values and watching the strategy
    deploy ~$3k per trade (10% × $30k)."""
    state = strategy_module.blank_state()
    state["bankroll"] = {"current_dollars": 90000.0}
    cfg = _cfg_with_daily_alloc(max_hold_days=3)
    assert strategy_module.get_sizing_basis(
        state, fallback_equity=0.0, cfg=cfg,
    ) == 30000.0


def test_get_sizing_basis_days_override_takes_precedence(strategy_module):
    """daily_allocation.days override beats exits.max_hold_days."""
    state = strategy_module.blank_state()
    state["bankroll"] = {"current_dollars": 90000.0}
    cfg = _cfg_with_daily_alloc(max_hold_days=3, da_days=5)
    assert strategy_module.get_sizing_basis(
        state, fallback_equity=0.0, cfg=cfg,
    ) == 18000.0


def test_get_sizing_basis_daily_alloc_disabled_returns_full_bankroll(strategy_module):
    state = strategy_module.blank_state()
    state["bankroll"] = {"current_dollars": 90000.0}
    cfg = _cfg_with_daily_alloc(max_hold_days=3, da_enabled=False)
    assert strategy_module.get_sizing_basis(
        state, fallback_equity=0.0, cfg=cfg,
    ) == 90000.0


def test_get_sizing_basis_no_cfg_returns_full_bankroll(strategy_module):
    """Old-style call without cfg arg → preserves prior behavior."""
    state = strategy_module.blank_state()
    state["bankroll"] = {"current_dollars": 90000.0}
    assert strategy_module.get_sizing_basis(
        state, fallback_equity=0.0,
    ) == 90000.0


def test_get_sizing_basis_daily_alloc_zero_days_falls_back_to_bankroll(
    strategy_module, caplog,
):
    """Misconfigured: enabled but max_hold_days unset / 0. Function
    falls back to the un-sliced bankroll with a logged warning,
    rather than dividing by zero or raising mid-session."""
    state = strategy_module.blank_state()
    state["bankroll"] = {"current_dollars": 90000.0}
    cfg = {
        "exits": {"max_hold_days": 0},
        "bankroll": {"daily_allocation": {"enabled": True, "days": None}},
    }
    with caplog.at_level("WARNING"):
        assert strategy_module.get_sizing_basis(
            state, fallback_equity=0.0, cfg=cfg,
        ) == 90000.0
    assert any("daily_allocation" in r.message for r in caplog.records)


def test_select_entries_decouples_per_trade_from_gross_cap(strategy_module):
    """gross_cap_basis overrides equity for the gross-exposure check
    only. Set per-trade basis to the daily slice ($30k) but gross
    basis to the full bankroll ($90k): per-trade size derives from
    the slice, gross deployment ceiling derives from the bankroll."""
    cfg = {
        "sizing": {
            "per_trade_pct": 0.10,
            "max_concurrent_positions": 20,
            "default_venue_code": "XNAS",
        },
        "risk": {
            "max_gross_exposure_pct": 0.50,
            "max_per_trade_dollars": None,
            "max_gross_exposure_dollars": None,
            "max_position_as_adv_frac": None,
        },
    }
    # 10 candidates @ $10 each. With slice=30k, per-trade = $3k →
    # 300 shares each, $3k notional each. Cumulative cap is 0.50 *
    # 90k = $45k. So at most 15 of these (15 * $3k = $45k) fit by
    # gross-cap. We give 10 candidates, all should fit.
    # ADV-tier-caps feature: stamp a permissive ADV so the ADV
    # check doesn't reject these synthetic candidates.
    _adv = {"avg_dollar_volume": 1_000_000_000.0}
    cands = [
        strategy_module.Candidate(
            f"T{i}", close=10.0, signal_strength=9.0 - i * 0.01,
            features=dict(_adv),
        )
        for i in range(10)
    ]
    state = strategy_module.blank_state()
    selected = strategy_module.select_entries(
        cands, state,
        equity=30_000.0,           # per-trade basis (daily slice)
        gross_cap_basis=90_000.0,  # gross-cap basis (full bankroll)
        latest_prices={}, cfg=cfg,
        kill_state=strategy_module.KillLevel.NONE,
    )
    # All 10 fit (cumulative $30k <= $45k gross cap).
    assert len(selected) == 10
    for e in selected:
        assert e.qty == 300  # $3k / $10
    # Same call WITHOUT gross_cap_basis (back-compat): gross cap is
    # computed against equity=$30k → 50% = $15k cumulative, so only
    # 5 trades fit ($15k = 5*$3k).
    state2 = strategy_module.blank_state()
    selected2 = strategy_module.select_entries(
        cands, state2,
        equity=30_000.0,
        latest_prices={}, cfg=cfg,
        kill_state=strategy_module.KillLevel.NONE,
    )
    assert len(selected2) == 5


def test_daily_allocation_per_trade_is_sliced(strategy_module):
    """Concrete worked example. Bankroll=$90k, max_hold=3 days → daily
    slice is $30k → per_trade_pct=0.10 × $30k = $3k per trade. Without
    daily_allocation, each trade would be $9k (0.10 × full bankroll).

    Demonstrates the mechanism the operator asked for: the per-trade
    dollar budget shrinks to a 1/max_hold_days fraction so every day
    has fresh capital to deploy."""
    cfg = {
        "sizing": {
            "per_trade_pct": 0.10,
            "max_concurrent_positions": 5,
            "default_venue_code": "XNAS",
        },
        "risk": {
            "max_gross_exposure_pct": 1.0,  # don't cap-block this test
            "max_per_trade_dollars": None,
            "max_gross_exposure_dollars": None,
            "max_position_as_adv_frac": None,
        },
        "exits": {"max_hold_days": 3},
        "bankroll": {"daily_allocation": {"enabled": True, "days": None}},
    }
    state = strategy_module.blank_state()
    state["bankroll"] = {"current_dollars": 90_000.0}
    cands = [strategy_module.Candidate(
        "AAPL", close=10.0, signal_strength=9.0,
        features={"avg_dollar_volume": 1_000_000_000.0},
    )]

    # With daily_allocation: $30k slice → 3000 shares at $10.
    basis_sliced = strategy_module.get_sizing_basis(state, 0.0, cfg=cfg)
    gross = strategy_module.get_bankroll_dollars(state, 0.0)
    assert basis_sliced == 30_000.0
    sliced = strategy_module.select_entries(
        cands, state, equity=basis_sliced, gross_cap_basis=gross,
        latest_prices={}, cfg=cfg,
        kill_state=strategy_module.KillLevel.NONE,
    )
    assert sliced[0].qty == 300  # $3k / $10 = 300 shares

    # Without daily_allocation: $90k basis → 900 shares (3× larger).
    cfg_no_alloc = dict(cfg)
    cfg_no_alloc["bankroll"] = {"daily_allocation": {"enabled": False}}
    basis_full = strategy_module.get_sizing_basis(
        state, 0.0, cfg=cfg_no_alloc,
    )
    assert basis_full == 90_000.0
    unsliced = strategy_module.select_entries(
        cands, state, equity=basis_full, gross_cap_basis=basis_full,
        latest_prices={}, cfg=cfg,
        kill_state=strategy_module.KillLevel.NONE,
    )
    assert unsliced[0].qty == 900  # $9k / $10 = 900 shares


def test_equal_slice_per_trade_overrides_pct(strategy_module):
    """sizing.equal_slice_per_position=true makes each trade
    bankroll/max_concurrent_positions, ignoring per_trade_pct. The
    user's exact case: bankroll=$90k, max_concurrent=18 →
    per-trade=$5,000. With close=$10, qty=500."""
    cfg = {
        "sizing": {
            "per_trade_pct": 0.10,  # ignored under equal_slice
            "max_concurrent_positions": 18,
            "default_venue_code": "XNAS",
            "equal_slice_per_position": True,
        },
        "risk": {
            "max_gross_exposure_pct": 1.0,
            "max_per_trade_dollars": None,
            "max_gross_exposure_dollars": None,
            "max_position_as_adv_frac": None,
        },
        "exits": {"max_hold_days": 3},
        "bankroll": {"daily_allocation": {"enabled": True, "days": None}},
    }
    state = strategy_module.blank_state()
    state["bankroll"] = {"current_dollars": 90_000.0}
    cand = strategy_module.Candidate(
        "AAPL", close=10.0, signal_strength=9.0,
        features={"avg_dollar_volume": 1_000_000_000.0},
    )
    sizing = strategy_module.get_sizing_basis(state, 0.0, cfg=cfg)
    gross = strategy_module.get_bankroll_dollars(state, 0.0)
    selected = strategy_module.select_entries(
        [cand], state, equity=sizing, gross_cap_basis=gross,
        latest_prices={}, cfg=cfg,
        kill_state=strategy_module.KillLevel.NONE,
    )
    assert len(selected) == 1
    assert selected[0].qty == 500  # $5000 / $10


def test_equal_slice_helper_returns_bankroll_over_concurrent(strategy_module):
    state = strategy_module.blank_state()
    state["bankroll"] = {"current_dollars": 90_000.0}
    cfg = {"sizing": {
        "max_concurrent_positions": 18,
        "equal_slice_per_position": True,
    }}
    target = strategy_module._per_trade_dollars_for_slate(
        state, cfg, fallback_equity=0.0,
    )
    assert target == pytest.approx(5000.0)


def test_equal_slice_disabled_returns_none(strategy_module):
    state = strategy_module.blank_state()
    state["bankroll"] = {"current_dollars": 90_000.0}
    cfg = {"sizing": {
        "max_concurrent_positions": 18,
        "equal_slice_per_position": False,
    }}
    assert strategy_module._per_trade_dollars_for_slate(
        state, cfg, fallback_equity=0.0,
    ) is None


def test_equal_slice_zero_max_concurrent_falls_back(strategy_module, caplog):
    """Misconfigured: equal_slice on but max_concurrent_positions is 0
    → fall back to per_trade_pct path with a warning. The strategy
    must NOT divide by zero or refuse to start."""
    state = strategy_module.blank_state()
    state["bankroll"] = {"current_dollars": 90_000.0}
    cfg = {"sizing": {
        "max_concurrent_positions": 0,
        "equal_slice_per_position": True,
    }}
    with caplog.at_level("WARNING"):
        out = strategy_module._per_trade_dollars_for_slate(
            state, cfg, fallback_equity=0.0,
        )
    assert out is None
    assert any("equal_slice_per_position" in r.message for r in caplog.records)


def test_equal_slice_with_no_bankroll_uses_fallback_equity(strategy_module):
    """No bankroll dict in state → fallback to broker equity for the
    slice calc. Operator gets equal-slice behavior even without the
    bankroll envelope."""
    state = strategy_module.blank_state()
    cfg = {"sizing": {
        "max_concurrent_positions": 10,
        "equal_slice_per_position": True,
    }}
    target = strategy_module._per_trade_dollars_for_slate(
        state, cfg, fallback_equity=100_000.0,
    )
    assert target == 10_000.0


def test_equal_slice_auto_couples_to_max_gross_exposure_pct(strategy_module):
    """The user's intent: with bankroll=$90k, max_concurrent=18, and
    max_gross_exposure_pct=0.80, per-trade should resolve to $4,000
    (= 0.80 × $90k / 18). No explicit fraction set → auto-couple to
    the gross-cap percent."""
    state = strategy_module.blank_state()
    state["bankroll"] = {"current_dollars": 90_000.0}
    cfg = {
        "sizing": {
            "max_concurrent_positions": 18,
            "equal_slice_per_position": True,
            # equal_slice_bankroll_fraction omitted → auto
        },
        "risk": {"max_gross_exposure_pct": 0.80},
    }
    target = strategy_module._per_trade_dollars_for_slate(
        state, cfg, fallback_equity=0.0,
    )
    assert target == pytest.approx(4000.0)


def test_equal_slice_explicit_fraction_overrides_auto(strategy_module):
    """Operator pinning a smaller fraction (e.g., for additional
    buffer) beats the auto-coupled value."""
    state = strategy_module.blank_state()
    state["bankroll"] = {"current_dollars": 90_000.0}
    cfg = {
        "sizing": {
            "max_concurrent_positions": 18,
            "equal_slice_per_position": True,
            "equal_slice_bankroll_fraction": 0.50,
        },
        "risk": {"max_gross_exposure_pct": 0.80},
    }
    target = strategy_module._per_trade_dollars_for_slate(
        state, cfg, fallback_equity=0.0,
    )
    # 0.50 × $90k / 18 = $2,500
    assert target == pytest.approx(2500.0)


def test_equal_slice_no_fraction_no_gross_cap_uses_full_bankroll(strategy_module):
    """Both unset → fraction = 1.0 (full bankroll). Preserves the
    pre-feature behavior of equal_slice for operators who haven't
    set a gross_cap percent."""
    state = strategy_module.blank_state()
    state["bankroll"] = {"current_dollars": 90_000.0}
    cfg = {
        "sizing": {
            "max_concurrent_positions": 18,
            "equal_slice_per_position": True,
        },
        "risk": {"max_gross_exposure_pct": None},
    }
    assert strategy_module._per_trade_dollars_for_slate(
        state, cfg, fallback_equity=0.0,
    ) == pytest.approx(5000.0)


def test_equal_slice_invalid_fraction_falls_back_to_auto(
    strategy_module, caplog,
):
    """Bad fraction → log warning + fall back to auto-couple."""
    state = strategy_module.blank_state()
    state["bankroll"] = {"current_dollars": 90_000.0}
    cfg = {
        "sizing": {
            "max_concurrent_positions": 18,
            "equal_slice_per_position": True,
            "equal_slice_bankroll_fraction": 1.5,  # out of range
        },
        "risk": {"max_gross_exposure_pct": 0.80},
    }
    with caplog.at_level("WARNING"):
        target = strategy_module._per_trade_dollars_for_slate(
            state, cfg, fallback_equity=0.0,
        )
    # Falls back to auto = 0.80 → $4,000.
    assert target == pytest.approx(4000.0)
    assert any(
        "equal_slice_bankroll_fraction" in r.message for r in caplog.records
    )


def test_equal_slice_negative_fraction_falls_back(strategy_module, caplog):
    state = strategy_module.blank_state()
    state["bankroll"] = {"current_dollars": 90_000.0}
    cfg = {
        "sizing": {
            "max_concurrent_positions": 10,
            "equal_slice_per_position": True,
            "equal_slice_bankroll_fraction": -0.5,
        },
        "risk": {"max_gross_exposure_pct": None},
    }
    with caplog.at_level("WARNING"):
        out = strategy_module._per_trade_dollars_for_slate(
            state, cfg, fallback_equity=0.0,
        )
    # Falls back through auto (also None) to 1.0 → $9k.
    assert out == pytest.approx(9000.0)


def test_equal_slice_scales_with_bankroll(strategy_module):
    """The compounding property the user asked for: as bankroll
    grows or shrinks, per-trade dollar size moves with it."""
    cfg = {
        "sizing": {
            "max_concurrent_positions": 18,
            "equal_slice_per_position": True,
        },
        "risk": {"max_gross_exposure_pct": 0.80},
    }
    # Drawdown: bankroll halves → per-trade halves.
    state = strategy_module.blank_state()
    state["bankroll"] = {"current_dollars": 45_000.0}
    assert strategy_module._per_trade_dollars_for_slate(
        state, cfg, fallback_equity=0.0,
    ) == pytest.approx(2000.0)  # 0.80 × 45k / 18

    # Growth toward cap.
    state["bankroll"] = {"current_dollars": 200_000.0}
    assert strategy_module._per_trade_dollars_for_slate(
        state, cfg, fallback_equity=0.0,
    ) == pytest.approx(8888.888888888889)  # 0.80 × 200k / 18


def test_equal_slice_auto_18_slots_fit_gross_cap_exactly(strategy_module):
    """The clean property of auto-coupling: 18 trades × per_trade =
    exactly max_gross_exposure_pct × bankroll. So all 18 slots fill
    without the gross-cap blocking the 15th, 16th, 17th, 18th."""
    cfg = {
        "sizing": {
            "per_trade_pct": 0.10,
            "max_concurrent_positions": 18,
            "default_venue_code": "XNAS",
            "equal_slice_per_position": True,
        },
        "risk": {
            "max_gross_exposure_pct": 0.80,
            "max_per_trade_dollars": None,
            "max_gross_exposure_dollars": None,
            "max_position_as_adv_frac": None,
        },
    }
    state = strategy_module.blank_state()
    state["bankroll"] = {"current_dollars": 90_000.0}
    # ADV-tier-caps feature: stamp a permissive ADV on every
    # synthetic candidate so the ADV gate doesn't reject them.
    _adv = {"avg_dollar_volume": 1_000_000_000.0}
    cands = [
        strategy_module.Candidate(
            f"T{i}", close=10.0, signal_strength=9.0 - i * 0.001,
            features=dict(_adv),
        )
        for i in range(30)
    ]
    sizing = strategy_module.get_sizing_basis(state, 0.0, cfg=cfg)
    gross = strategy_module.get_bankroll_dollars(state, 0.0)
    selected = strategy_module.select_entries(
        cands, state, equity=sizing, gross_cap_basis=gross,
        latest_prices={}, cfg=cfg,
        kill_state=strategy_module.KillLevel.NONE,
    )
    assert len(selected) == 18  # max_concurrent_positions exactly
    for e in selected:
        assert e.qty == 400  # $4k / $10
    total = sum(e.qty * e.close_price for e in selected)
    assert total == pytest.approx(72_000.0)  # exactly the cap


def test_equal_slice_full_bankroll_deployment_simulation(strategy_module):
    """With bankroll=$90k, max_concurrent=18, equal_slice ON, and
    gross-cap=1.0 (full bankroll): the slate fills exactly 18 entries
    of $5k each, summing to $90k = the full bankroll. This is the
    operator's design intent for steady-state full utilization."""
    cfg = {
        "sizing": {
            "per_trade_pct": 0.10,
            "max_concurrent_positions": 18,
            "default_venue_code": "XNAS",
            "equal_slice_per_position": True,
        },
        "risk": {
            "max_gross_exposure_pct": 1.0,
            "max_per_trade_dollars": None,
            "max_gross_exposure_dollars": None,
            "max_position_as_adv_frac": None,
        },
        "exits": {"max_hold_days": 3},
        "bankroll": {"daily_allocation": {"enabled": True, "days": None}},
    }
    state = strategy_module.blank_state()
    state["bankroll"] = {"current_dollars": 90_000.0}
    # ADV-tier-caps feature: stamp a permissive ADV.
    _adv = {"avg_dollar_volume": 1_000_000_000.0}
    cands = [
        strategy_module.Candidate(
            f"T{i}", close=10.0, signal_strength=9.0 - i * 0.001,
            features=dict(_adv),
        )
        for i in range(30)
    ]
    sizing = strategy_module.get_sizing_basis(state, 0.0, cfg=cfg)
    gross = strategy_module.get_bankroll_dollars(state, 0.0)
    selected = strategy_module.select_entries(
        cands, state, equity=sizing, gross_cap_basis=gross,
        latest_prices={}, cfg=cfg,
        kill_state=strategy_module.KillLevel.NONE,
    )
    assert len(selected) == 18  # max_concurrent_positions
    for e in selected:
        assert e.qty == 500  # $5k / $10
    total_notional = sum(e.qty * e.close_price for e in selected)
    assert total_notional == pytest.approx(90_000.0)  # full bankroll


def test_equal_slice_respects_adv_cap(strategy_module):
    """ADV cap still applies — equal_slice doesn't bypass the
    capacity constraint. A thin-ADV name gets fewer shares than the
    nominal slice would allow."""
    cfg = {
        "sizing": {
            "per_trade_pct": 0.10,
            "max_concurrent_positions": 10,
            "default_venue_code": "XNAS",
            "equal_slice_per_position": True,
        },
        "risk": {
            "max_gross_exposure_pct": 1.0,
            "max_per_trade_dollars": None,
            "max_gross_exposure_dollars": None,
            # 3% of avg_dollar_volume — for low-ADV names this caps
            # the position smaller than the equal slice.
            "max_position_as_adv_frac": 0.03,
        },
    }
    state = strategy_module.blank_state()
    state["bankroll"] = {"current_dollars": 100_000.0}
    # Equal slice = $100k/10 = $10k per trade.
    # Low-ADV candidate: avg_dollar_volume = $200k → 3% cap = $6k.
    # ADV cap should bind, producing $6k notional.
    cand = strategy_module.Candidate(
        "TINY", close=10.0, signal_strength=9.0,
        features={"avg_dollar_volume": 200_000.0},
    )
    selected = strategy_module.select_entries(
        [cand], state, equity=10_000.0, gross_cap_basis=100_000.0,
        latest_prices={}, cfg=cfg,
        kill_state=strategy_module.KillLevel.NONE,
    )
    assert len(selected) == 1
    assert selected[0].qty == 600  # $6k / $10


def test_daily_allocation_steady_state_capacity(strategy_module):
    """With max_concurrent_positions bumped to max_concurrent_per_day
    × max_hold_days, the strategy reaches steady-state full deployment:
    Day 1 fires 5, Day 2 fires up to 10 more (gross cap allowing),
    Day 3 fills the rest of the gross-cap envelope. The user can tune
    max_gross_exposure_pct (1.0 for full bankroll deployment) to set
    the cumulative ceiling."""
    cfg = {
        "sizing": {
            "per_trade_pct": 0.10,
            "max_concurrent_positions": 15,  # 5/day × 3 days
            "default_venue_code": "XNAS",
        },
        "risk": {
            "max_gross_exposure_pct": 1.0,  # use full bankroll
            "max_per_trade_dollars": None,
            "max_gross_exposure_dollars": None,
            "max_position_as_adv_frac": None,
        },
        "exits": {"max_hold_days": 3},
        "bankroll": {"daily_allocation": {"enabled": True, "days": None}},
    }
    state = strategy_module.blank_state()
    state["bankroll"] = {"current_dollars": 90_000.0}
    # ADV-tier-caps feature: stamp a permissive ADV.
    _adv = {"avg_dollar_volume": 1_000_000_000.0}
    cands = [
        strategy_module.Candidate(
            f"T{i}", close=10.0, signal_strength=9.0 - i * 0.01,
            features=dict(_adv),
        )
        for i in range(30)
    ]
    sizing = strategy_module.get_sizing_basis(state, 0.0, cfg=cfg)
    gross = strategy_module.get_bankroll_dollars(state, 0.0)

    # Day 1: empty state, sizing slice = $30k, gross cap = $90k
    # → cumulative limit of 30 trades × $3k = $90k. But max_concurrent
    # caps at 15. Expect 15.
    day1 = strategy_module.select_entries(
        cands, state, equity=sizing, gross_cap_basis=gross,
        latest_prices={}, cfg=cfg,
        kill_state=strategy_module.KillLevel.NONE,
    )
    assert len(day1) == 15
    total_day1_notional = sum(e.qty * e.close_price for e in day1)
    # 15 × $3k = $45k, half the bankroll (one slice ahead — the
    # remaining $45k is what the user's gross cap leaves for Days 2-3
    # in steady state).
    assert total_day1_notional == pytest.approx(45_000.0)
