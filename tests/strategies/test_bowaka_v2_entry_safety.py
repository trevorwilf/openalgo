"""Hardening Phase 1 — entry-path safety.

Covers:
- live-mode quote-fetch failure rejects with ``quote_stale`` (no
  synthesized fallback around a real order),
- offline mode (submit_supplier=None) is decision telemetry only —
  no position recorded, no counters mutated,
- missing/zero signal price rejects with ``invalid_signal_price``,
- the pending-fill janitor expires aged pending lots, cancels their
  parents, and restores reserved exposure.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import pytest

import bowaka_v2_schemas as schemas
import bowaka_v2_strategy as v2


def _candidate(symbol: str, *, session_date: str = "2026-05-18",
               last_price: float | None = 8.11) -> dict:
    scan_ts = f"{session_date}T14:35:00Z"
    return {
        "schema_version": schemas.CANDIDATE_EVENT_SCHEMA_VERSION,
        "strategy": "bowaka_v2",
        "event_type": "candidate_signal",
        "event_id": f"bowaka_v2:{session_date}:{symbol}:{scan_ts}",
        "generated_at": scan_ts,
        "session_date": session_date,
        "scan_timestamp": scan_ts,
        "provider": "alpaca", "data_feed": "iex", "bar_interval": "1m",
        "config_hash": "sha256:t", "universe_hash": "sha256:t",
        "symbol": symbol, "exchange": "NASDAQ", "venue_code": "XNAS",
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
            "session_low": 7.50, "last_price": last_price,
            "session_volume": 820000, "session_range": 0.70,
            "last_bar_timestamp": f"{session_date}T18:34:00Z",
        },
        "intraday_volume_context": {
            "volume_curve_fraction": 0.42,
            "expected_volume_until_scan": 189000,
            "rvol_so_far": 4.34, "projected_full_day_rvol": 4.34,
        },
        "features": {
            "gap_pct": 0.0256, "current_return_pct": 0.1482,
            "range_expansion_so_far": 1.346,
            "close_location_so_far": 0.871,
            "ema_distance": 0.128, "ema_slope": 0.0199,
            "signal_strength": 7.82,
        },
        "gate_results": {
            "price_gate": True, "avg_dollar_volume_gate": True,
            "rvol_gate": True, "prior_atr_pct_gate": True,
            "range_expansion_gate": True, "close_location_gate": True,
            "ema_distance_gate": True, "ema_slope_gate": True,
            "max_gap_gate": True, "instrument_gate": True,
        },
        "candidate_rank": 1,
        "signal_expiry_timestamp": f"{session_date}T23:59:00Z",
    }


def _cfg(tmp_path: Path) -> dict:
    return {
        "strategy": {"mode": "forming_daily_bar_monitor",
                     "environment": "paper"},
        "paths": {
            "candidate_events_path": str(tmp_path / "candidates.jsonl"),
            "trade_ledger_path": str(tmp_path / "trade_ledger.jsonl"),
            "daily_summary_path": str(tmp_path / "daily_summary.jsonl"),
        },
        "data": {"feed": "iex", "allow_non_sip_for_research_only": True},
        "execution": {
            "default_venue_code": "XNAS",
            "parent_order_style": "market",
            "pending_fill_timeout_seconds": 900,
            "quote_gate": {"enabled": True, "max_spread_pct": 0.05,
                           "max_quote_age_seconds": 30,
                           "require_bid_ask_positive": True},
            "price_chase_gate": {"enabled": False},
            "halt_gate": {"enabled": False},
        },
        "sizing": {
            "sizing_mode": "equal_slice",
            "bankroll_fixed_dollars": 90000,
            "max_concurrent_positions": 18,
            "equal_slice_bankroll_fraction": 0.80,
            "min_order_notional": 500,
        },
        "risk": {"max_total_entries_per_day": 10,
                 "max_gross_exposure_pct": 0.80},
        "exits": {"stop_pct": 0.08, "target_pct": 0.15,
                  "max_hold_days": 3},
        "logging": {
            "emit_entry_decisions": True,
            "emit_rejected_candidates": True,
            "log_order_execution_quality": False,
            "log_protection_state": False,
            "log_shadow_risk_controls": False,
            "log_counterfactual_entries": False,
            "log_counterfactual_exits": False,
            "persist_config_snapshot": False,
        },
    }


@pytest.fixture(autouse=True)
def _redirect_v2_paths(tmp_path, monkeypatch):
    import bowaka_v2_paths as p
    monkeypatch.setattr(p, "ENTRY_DECISIONS_PATH",
                        tmp_path / "entry_decisions.jsonl")
    monkeypatch.setattr(p, "REJECTED_CANDIDATES_PATH",
                        tmp_path / "rejected_candidates.jsonl")


def _fresh_state() -> dict:
    return {"last_consumed_event_offset": 0, "entered_today": [],
            "daily_entries_count": 0, "open_positions": {},
            "gross_exposure_dollars": 0.0}


def _write(path: Path, events: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "a", encoding="utf-8") as f:
        for ev in events:
            f.write(json.dumps(ev) + "\n")


_NOW = datetime(2026, 5, 18, 18, 35, tzinfo=timezone.utc)


def _decisions(tmp_path: Path) -> list[dict]:
    import bowaka_v2_paths as p
    if not p.ENTRY_DECISIONS_PATH.exists():
        return []
    return [json.loads(l) for l in
            p.ENTRY_DECISIONS_PATH.read_text().splitlines()]


# ---- 1a: live quote-fetch failure rejects ----------------------------


def test_live_quote_supplier_none_rejects_quote_stale(tmp_path):
    cfg = _cfg(tmp_path)
    state = _fresh_state()
    _write(Path(cfg["paths"]["candidate_events_path"]),
           [_candidate("AAA")])
    s = v2.consume_candidate_events(
        state, cfg,
        quote_supplier=lambda sym: None,           # live fetch fails
        submit_supplier=lambda sym, qty: pytest.fail(
            "must not submit on failed quote"),
        today_iso="2026-05-18", now_utc=_NOW,
    )
    assert s["rejected"] == 1 and s["accepted"] == 0
    assert state["open_positions"] == {}
    recs = _decisions(tmp_path)
    assert recs and recs[0]["decision"] == "rejected"
    assert recs[0]["reason"] == "quote_stale"


def test_offline_quote_still_synthesized_for_telemetry(tmp_path):
    """No quote_supplier at all (offline) — the synthesized quote lets
    the decision pipeline run; no position is recorded without a
    submit_supplier."""
    cfg = _cfg(tmp_path)
    state = _fresh_state()
    _write(Path(cfg["paths"]["candidate_events_path"]),
           [_candidate("AAA")])
    s = v2.consume_candidate_events(
        state, cfg, today_iso="2026-05-18", now_utc=_NOW,
    )
    assert s["accepted"] == 1
    recs = _decisions(tmp_path)
    assert recs[0]["decision"] == "accepted"


# ---- 1b: offline mode never mutates position state --------------------


def test_offline_accept_is_log_only(tmp_path):
    cfg = _cfg(tmp_path)
    state = _fresh_state()
    _write(Path(cfg["paths"]["candidate_events_path"]),
           [_candidate("AAA"), _candidate("BBB")])
    s = v2.consume_candidate_events(
        state, cfg, today_iso="2026-05-18", now_utc=_NOW,
    )
    assert s["accepted"] == 2
    # State untouched except the consumer offset.
    assert state["open_positions"] == {}
    assert state["entered_today"] == []
    assert state["daily_entries_count"] == 0
    assert state["gross_exposure_dollars"] == 0.0
    assert state["last_consumed_event_offset"] > 0
    for rec in _decisions(tmp_path):
        assert rec["decision"] == "accepted"
        assert rec["execution"] == "skipped_no_supplier"


def test_live_accept_has_no_skip_marker(tmp_path):
    cfg = _cfg(tmp_path)
    state = _fresh_state()
    _write(Path(cfg["paths"]["candidate_events_path"]),
           [_candidate("AAA")])
    quote = {"bid": 8.10, "ask": 8.12, "mid": 8.11, "spread_pct": 0.002,
             "quote_timestamp": "2026-05-18T18:35:00Z",
             "quote_age_seconds": 1}
    s = v2.consume_candidate_events(
        state, cfg,
        quote_supplier=lambda sym: dict(quote),
        submit_supplier=lambda sym, qty: {
            "_http_status": 200, "data": {"order_id": f"P-{sym}"}},
        today_iso="2026-05-18", now_utc=_NOW,
    )
    assert s["accepted"] == 1
    assert len(state["open_positions"]) == 1
    assert state["daily_entries_count"] == 1
    rec = _decisions(tmp_path)[0]
    assert "execution" not in rec
    pos = v2.lots_for_symbol(state, "AAA")[0]
    assert pos["recorded_exposure"] == pytest.approx(
        pos["qty"] * 8.11)


# ---- 1c: invalid signal price -----------------------------------------


@pytest.mark.parametrize("bad_price", [None, 0, -3.2, True])
def test_invalid_signal_price_rejects(tmp_path, bad_price):
    cfg = _cfg(tmp_path)
    state = _fresh_state()
    _write(Path(cfg["paths"]["candidate_events_path"]),
           [_candidate("AAA", last_price=bad_price)])
    s = v2.consume_candidate_events(
        state, cfg,
        quote_supplier=lambda sym: pytest.fail(
            "must not fetch a quote for an unpriceable candidate"),
        submit_supplier=lambda sym, qty: pytest.fail("must not submit"),
        today_iso="2026-05-18", now_utc=_NOW,
    )
    assert s["rejected"] == 1
    assert state["open_positions"] == {}
    recs = _decisions(tmp_path)
    assert recs[0]["reason"] == "invalid_signal_price"
    assert "invalid_signal_price" in schemas.CANONICAL_REJECTION_REASONS


def test_size_position_zero_for_nonpositive_price():
    qty, notional = v2.size_position(
        {}, {"sizing": {"bankroll_fixed_dollars": 90000}},
        current_price=0.0,
    )
    assert (qty, notional) == (0, 0.0)


# ---- 1d: pending-fill janitor -----------------------------------------


class _FakeOA:
    def __init__(self):
        self.canceled: list[str] = []

    def cancel_order(self, http, api_key, order_id):
        self.canceled.append(order_id)
        return {"status": "canceled", "order_id": order_id}


def _pending_lot(symbol: str, *, entry_ts: str, parent: str = "P-1",
                 exposure: float = 4000.0) -> dict:
    return {
        "symbol": symbol, "qty": 100, "venue_code": "XNAS",
        "parent_order_id": parent, "link_id": f"BOWAKAv2-{symbol}-1",
        "child_order_ids": {"target": "", "stop": ""},
        "status": "pending_fill", "entry_price": None,
        "entry_timestamp": entry_ts, "recorded_exposure": exposure,
        "stop_pct": 0.08, "target_pct": 0.15, "max_hold_days": 3,
    }


def test_janitor_expires_aged_pending_lot(tmp_path):
    cfg = _cfg(tmp_path)
    now = datetime(2026, 5, 18, 19, 0, tzinfo=timezone.utc)
    state = {
        "gross_exposure_dollars": 4000.0,
        "open_positions": {
            "L-old": _pending_lot(
                "AAA", entry_ts="2026-05-18T18:30:00Z", parent="P-old",
            ),
        },
    }
    oa = _FakeOA()
    out = v2.expire_stale_pending_fills(
        state, cfg, oa_client=oa, api_key="k", http=None, now_utc=now,
    )
    assert out == ["AAA"]
    assert state["open_positions"] == {}
    assert state["gross_exposure_dollars"] == 0.0
    assert oa.canceled == ["P-old"]
    ledger = Path(cfg["paths"]["trade_ledger_path"]).read_text()
    events = [json.loads(l) for l in ledger.splitlines()]
    assert any(e["event_type"] == "pending_fill_expired" for e in events)


def test_janitor_leaves_fresh_pending_lot(tmp_path):
    cfg = _cfg(tmp_path)
    now = datetime(2026, 5, 18, 18, 40, tzinfo=timezone.utc)
    state = {
        "gross_exposure_dollars": 4000.0,
        "open_positions": {
            "L-new": _pending_lot(
                "BBB", entry_ts="2026-05-18T18:35:00Z",
            ),
        },
    }
    oa = _FakeOA()
    out = v2.expire_stale_pending_fills(
        state, cfg, oa_client=oa, api_key="k", http=None, now_utc=now,
    )
    assert out == []
    assert "L-new" in state["open_positions"]
    assert oa.canceled == []
    assert state["gross_exposure_dollars"] == 4000.0


def test_janitor_skips_cancel_for_empty_parent_id(tmp_path):
    cfg = _cfg(tmp_path)
    now = datetime(2026, 5, 18, 20, 0, tzinfo=timezone.utc)
    state = {
        "gross_exposure_dollars": 4000.0,
        "open_positions": {
            "L-x": _pending_lot(
                "CCC", entry_ts="2026-05-18T18:30:00Z", parent="",
            ),
        },
    }
    oa = _FakeOA()
    out = v2.expire_stale_pending_fills(
        state, cfg, oa_client=oa, api_key="k", http=None, now_utc=now,
    )
    assert out == ["CCC"]
    assert oa.canceled == []
    assert state["open_positions"] == {}


def test_janitor_ignores_filled_lots(tmp_path):
    cfg = _cfg(tmp_path)
    now = datetime(2026, 5, 18, 20, 0, tzinfo=timezone.utc)
    lot = _pending_lot("DDD", entry_ts="2026-05-18T18:30:00Z")
    lot["status"] = "filled"
    state = {"gross_exposure_dollars": 4000.0,
             "open_positions": {"L-f": lot}}
    oa = _FakeOA()
    out = v2.expire_stale_pending_fills(
        state, cfg, oa_client=oa, api_key="k", http=None, now_utc=now,
    )
    assert out == []
    assert "L-f" in state["open_positions"]
