"""Fix Phase 4 — idempotent submits via client_order_id.

Covers:
- client submit bodies carry client_order_id when given / omit when
  None,
- consume passes the pre-generated link_id to 4-arg suppliers and
  records it on the lot; legacy 2-/3-arg suppliers keep working,
- a raised submit records an outcome_unresolved lot, persists state,
  and blocks subsequent entries (unresolved_order_outcome),
- resolve_unknown_submits adopts on client_order_id match and drops
  (exposure restored) after 12 consecutive misses,
- exit sells use deterministic {link_id}-EXIT{n} ids: n advances only
  on confirmed rejection; an existing order with the same id is
  adopted instead of re-sold.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone

import httpx
import pytest

import bowaka_v2_openalgo_client as oa
import bowaka_v2_schemas as schemas
import bowaka_v2_strategy as v2


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


def _ledger_events(tmp_path) -> list[dict]:
    p = tmp_path / "trade_ledger.jsonl"
    if not p.exists():
        return []
    return [json.loads(line) for line in
            p.read_text(encoding="utf-8").splitlines() if line.strip()]


# ---- client bodies -------------------------------------------------------------


@pytest.mark.parametrize("fn_name,extra", [
    ("submit_market_buy", {}),
    ("submit_market_sell", {}),
    ("submit_limit_buy", {"price": 10.5}),
    ("submit_limit_sell", {"price": 10.5}),
])
def test_client_body_carries_client_order_id(fn_name, extra):
    captured: dict = {}

    def handler(req: httpx.Request) -> httpx.Response:
        captured.update(json.loads(req.content.decode()))
        return httpx.Response(200, json={"data": {"order_id": "O-1"}})

    fn = getattr(oa, fn_name)
    with oa.make_http_client(
        "http://oa.test", transport=httpx.MockTransport(handler),
    ) as http:
        fn(http, "k", venue_code="XNAS", symbol="AAA", qty=10,
           client_order_id="COID-1", **extra)
    assert captured["client_order_id"] == "COID-1"


@pytest.mark.parametrize("fn_name,extra", [
    ("submit_market_buy", {}),
    ("submit_limit_sell", {"price": 10.5}),
])
def test_client_body_omits_client_order_id_when_none(fn_name, extra):
    captured: dict = {}

    def handler(req: httpx.Request) -> httpx.Response:
        captured.update(json.loads(req.content.decode()))
        return httpx.Response(200, json={"data": {"order_id": "O-1"}})

    fn = getattr(oa, fn_name)
    with oa.make_http_client(
        "http://oa.test", transport=httpx.MockTransport(handler),
    ) as http:
        fn(http, "k", venue_code="XNAS", symbol="AAA", qty=10, **extra)
    assert "client_order_id" not in captured


# ---- consume: link_id to supplier + recorded on lot -----------------------------


def _make_candidate(symbol: str, rank: int = 1) -> dict:
    return {
        "schema_version": schemas.CANDIDATE_EVENT_SCHEMA_VERSION,
        "strategy": "bowaka_v2",
        "event_type": "candidate_signal",
        "event_id": f"bowaka_v2:2026-05-18:{symbol}:scan",
        "generated_at": "2026-05-18T14:35:00Z",
        "session_date": "2026-05-18",
        "scan_timestamp": "2026-05-18T14:35:00Z",
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
            "session_low": 7.50, "last_price": 8.11,
            "session_volume": 820000, "session_range": 0.70,
            "last_bar_timestamp": "2026-05-18T18:34:00Z",
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
        "candidate_rank": rank,
        "signal_expiry_timestamp": "2026-05-19T00:00:00Z",
    }


def _consumer_cfg(tmp_path, cand_path, *, emit_rejections=False):
    return {
        "strategy": {"mode": "forming_daily_bar_monitor",
                       "environment": "paper"},
        "paths": {
            "candidate_events_path": str(cand_path),
            "trade_ledger_path": str(tmp_path / "trade_ledger.jsonl"),
            "daily_summary_path": str(tmp_path / "daily_summary.jsonl"),
        },
        "data": {"feed": "iex", "allow_non_sip_for_research_only": True},
        "execution": {
            "default_venue_code": "XNAS", "parent_order_style": "market",
            "quote_gate": {"enabled": False},
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
        "logging": {"emit_entry_decisions": False,
                       "emit_rejected_candidates": emit_rejections,
                       "log_order_execution_quality": False,
                       "log_protection_state": False,
                       "log_shadow_risk_controls": False,
                       "log_counterfactual_entries": False,
                       "log_counterfactual_exits": False},
    }


_NOW = datetime(2026, 5, 18, 18, 35, tzinfo=timezone.utc)
_QUOTE = {
    "bid": 8.10, "ask": 8.12, "mid": 8.11, "spread_pct": 0.002,
    "quote_timestamp": "2026-05-18T18:35:00Z",
    "quote_age_seconds": 1, "symbol_status": "ok",
}


def _fresh_state():
    return {"last_consumed_event_offset": 0, "entered_today": [],
            "daily_entries_count": 0, "open_positions": {}}


def test_four_arg_supplier_receives_link_id_and_pos_records_it(tmp_path):
    cand = tmp_path / "candidates.jsonl"
    cand.write_text(json.dumps(_make_candidate("AAA")) + "\n")
    cfg = _consumer_cfg(tmp_path, cand)
    state = _fresh_state()
    seen: dict = {}

    def supplier(symbol, qty, quote, link_id):
        seen["link_id"] = link_id
        seen["quote"] = quote
        return {"_http_status": 200, "data": {"order_id": "P-AAA"}}

    s = v2.consume_candidate_events(
        state, cfg, quote_supplier=lambda sym: dict(_QUOTE),
        submit_supplier=supplier, today_iso="2026-05-18", now_utc=_NOW,
    )
    assert s["accepted"] == 1
    pos = v2.lots_for_symbol(state, "AAA")[0]
    assert seen["link_id"] == pos["link_id"]
    assert pos["client_order_id"] == pos["link_id"]
    assert seen["link_id"].startswith("BOWAKAv2-AAA-")
    assert seen["quote"]["ask"] == 8.12


def test_legacy_two_and_three_arg_suppliers_still_work(tmp_path):
    for supplier, expect_quote in (
        (lambda sym, qty: {"_http_status": 200,
                            "data": {"order_id": "P-1"}}, False),
        (lambda sym, qty, quote: {"_http_status": 200,
                                   "data": {"order_id": "P-1"}}, True),
    ):
        cand = tmp_path / f"candidates_{expect_quote}.jsonl"
        cand.write_text(json.dumps(_make_candidate("AAA")) + "\n")
        cfg = _consumer_cfg(tmp_path, cand)
        state = _fresh_state()
        s = v2.consume_candidate_events(
            state, cfg, quote_supplier=lambda sym: dict(_QUOTE),
            submit_supplier=supplier, today_iso="2026-05-18",
            now_utc=_NOW,
        )
        assert s["accepted"] == 1, supplier


# ---- unknown-outcome recording ---------------------------------------------------


def test_raised_submit_records_unresolved_and_blocks_next_entry(tmp_path):
    cand = tmp_path / "candidates.jsonl"
    cand.write_text(
        json.dumps(_make_candidate("AAA", rank=1)) + "\n"
        + json.dumps(_make_candidate("BBB", rank=2)) + "\n",
    )
    state_path = tmp_path / "state.json"
    cfg = _consumer_cfg(tmp_path, cand, emit_rejections=True)
    state = _fresh_state()

    def supplier(symbol, qty, quote, link_id):
        if symbol == "AAA":
            raise ConnectionError("socket dropped mid-request")
        return {"_http_status": 200, "data": {"order_id": f"P-{symbol}"}}

    s = v2.consume_candidate_events(
        state, cfg, quote_supplier=lambda sym: dict(_QUOTE),
        submit_supplier=supplier, today_iso="2026-05-18", now_utc=_NOW,
        state_path=state_path,
    )
    assert s["unresolved"] == 1
    assert s["accepted"] == 0
    assert s["rejected"] == 1        # BBB blocked by the unresolved lot
    lots = v2.lots_for_symbol(state, "AAA")
    assert len(lots) == 1
    pos = lots[0]
    assert pos["outcome_unresolved"] is True
    assert pos["parent_order_id"] == ""
    assert pos["client_order_id"] == pos["link_id"]
    # Persisted immediately.
    persisted = json.loads(state_path.read_text(encoding="utf-8"))
    assert any(p.get("outcome_unresolved")
               for p in persisted["open_positions"].values())
    # Ledger records the unknown.
    assert any(e["event_type"] == "submit_outcome_unknown"
               for e in _ledger_events(tmp_path))
    # BBB's rejection reason is the new canonical one.
    rejected = [json.loads(line) for line in
                (tmp_path / "rejected_candidates.jsonl")
                .read_text(encoding="utf-8").splitlines()]
    assert [r["reason"] for r in rejected if r["symbol"] == "BBB"] \
        == ["unresolved_order_outcome"]
    assert "unresolved_order_outcome" in schemas.CANONICAL_REJECTION_REASONS


def test_accepted_without_order_id_records_unresolved(tmp_path):
    cand = tmp_path / "candidates.jsonl"
    cand.write_text(json.dumps(_make_candidate("AAA")) + "\n")
    cfg = _consumer_cfg(tmp_path, cand)
    state = _fresh_state()
    s = v2.consume_candidate_events(
        state, cfg, quote_supplier=lambda sym: dict(_QUOTE),
        submit_supplier=lambda sym, qty: {"_http_status": 200,
                                           "data": {}},
        today_iso="2026-05-18", now_utc=_NOW,
    )
    assert s["unresolved"] == 1
    pos = v2.lots_for_symbol(state, "AAA")[0]
    assert pos["outcome_unresolved"] is True


def test_clean_rejection_still_records_no_lot(tmp_path):
    cand = tmp_path / "candidates.jsonl"
    cand.write_text(json.dumps(_make_candidate("AAA")) + "\n")
    cfg = _consumer_cfg(tmp_path, cand)
    state = _fresh_state()
    s = v2.consume_candidate_events(
        state, cfg, quote_supplier=lambda sym: dict(_QUOTE),
        submit_supplier=lambda sym, qty: {"_http_status": 403,
                                           "error": {"m": "rejected"}},
        today_iso="2026-05-18", now_utc=_NOW,
    )
    assert s["rejected"] == 1
    assert s["unresolved"] == 0
    assert state["open_positions"] == {}


# ---- resolver ---------------------------------------------------------------------


class ResolverOA:
    def __init__(self, rows=None):
        self.rows = rows or []

    def fetch_all_orders(self, http, api_key):
        return list(self.rows)


def _unresolved_lot(symbol="AAA", link_id="L-1", exposure=4000.0):
    return {
        "symbol": symbol, "qty": 400, "status": "pending_fill",
        "link_id": link_id, "client_order_id": link_id,
        "parent_order_id": "", "outcome_unresolved": True,
        "resolver_misses": 0, "recorded_exposure": exposure,
        "child_order_ids": {"target": "", "stop": ""},
        "entry_timestamp": "2026-05-18T18:30:00Z",
    }


def test_resolver_adopts_on_client_order_id_match(tmp_path):
    cfg = _consumer_cfg(tmp_path, tmp_path / "unused.jsonl")
    state = {"gross_exposure_dollars": 4000.0,
             "open_positions": {"L-1": _unresolved_lot()}}
    oa_fake = ResolverOA(rows=[
        {"id": "P-9", "client_order_id": "L-1", "status": "new"},
    ])
    out = v2.resolve_unknown_submits(
        state, cfg, oa_client=oa_fake, api_key="k", http=None,
    )
    assert out == ["L-1"]
    pos = state["open_positions"]["L-1"]
    assert pos["parent_order_id"] == "P-9"
    assert "outcome_unresolved" not in pos
    assert any(e["event_type"] == "unknown_submit_resolved_present"
               for e in _ledger_events(tmp_path))
    # Entries unblock once nothing is unresolved.
    assert v2._risk_gates(
        {"symbol": "ZZZ"}, state, cfg,
        candidate_adv=None, target_notional=100.0,
    ) != "unresolved_order_outcome"


def test_resolver_drops_after_12_misses_with_exposure_restore(tmp_path):
    cfg = _consumer_cfg(tmp_path, tmp_path / "unused.jsonl")
    state = {"gross_exposure_dollars": 4000.0,
             "open_positions": {"L-1": _unresolved_lot()}}
    oa_fake = ResolverOA(rows=[])
    for i in range(11):
        assert v2.resolve_unknown_submits(
            state, cfg, oa_client=oa_fake, api_key="k", http=None,
        ) == []
        assert "L-1" in state["open_positions"]
        # Still blocking entries while unresolved.
        assert v2._risk_gates(
            {"symbol": "ZZZ"}, state, cfg,
            candidate_adv=None, target_notional=100.0,
        ) == "unresolved_order_outcome"
    out = v2.resolve_unknown_submits(
        state, cfg, oa_client=oa_fake, api_key="k", http=None,
    )
    assert out == ["L-1"]
    assert state["open_positions"] == {}
    assert state["gross_exposure_dollars"] == 0.0
    assert any(e["event_type"] == "unknown_submit_resolved_absent"
               for e in _ledger_events(tmp_path))


def test_janitor_skips_unresolved_lots(tmp_path):
    cfg = _consumer_cfg(tmp_path, tmp_path / "unused.jsonl")
    cfg["execution"]["pending_fill_timeout_seconds"] = 1
    state = {"gross_exposure_dollars": 4000.0,
             "open_positions": {"L-1": _unresolved_lot()}}

    class JanitorOA(ResolverOA):
        def cancel_order(self, http, api_key, order_id):  # pragma: no cover
            raise AssertionError("janitor must not touch unresolved lots")

    out = v2.expire_stale_pending_fills(
        state, cfg, oa_client=JanitorOA(), api_key="k", http=None,
        now_utc=datetime(2026, 5, 18, 20, 0, tzinfo=timezone.utc),
    )
    assert out == []
    assert "L-1" in state["open_positions"]


# ---- exit idempotency ---------------------------------------------------------------


class SellOA:
    """Sell-capturing oa_client; children resolve canceled instantly."""

    def __init__(self):
        self.sells: list[dict] = []
        self.sell_responses: list[dict] = []
        self.rows: list[dict] = []

    def cancel_order(self, http, api_key, order_id):
        return {"status": "canceled", "order_id": order_id}

    def fetch_order(self, http, api_key, order_id):
        return {"id": order_id, "status": "canceled", "filled_qty": 0}

    def fetch_all_orders(self, http, api_key):
        return list(self.rows)

    def submit_market_sell(self, http, api_key, *, venue_code, symbol,
                            qty, time_in_force="DAY",
                            client_order_id=None):
        self.sells.append({"symbol": symbol, "qty": qty,
                            "client_order_id": client_order_id})
        return self.sell_responses.pop(0) if self.sell_responses else {
            "data": {"order_id": "EXIT-1"}, "_http_status": 200,
        }

    def submit_limit_sell(self, http, api_key, *, venue_code, symbol,
                           qty, price, time_in_force="DAY",
                           client_order_id=None):
        return self.submit_market_sell(
            http, api_key, venue_code=venue_code, symbol=symbol,
            qty=qty, time_in_force=time_in_force,
            client_order_id=client_order_id,
        )


def _exit_cfg(tmp_path):
    return {
        "paths": {
            "trade_ledger_path": str(tmp_path / "trade_ledger.jsonl"),
            "daily_summary_path": str(tmp_path / "daily_summary.jsonl"),
        },
        "execution": {"default_venue_code": "XNAS"},
        "exits": {"stop_pct": 0.05, "target_pct": 0.10,
                  "max_hold_days": 2, "oco_time_in_force": "GTC"},
        "logging": {"log_protection_state": True},
    }


def _exit_lot():
    return {
        "symbol": "AAA", "qty": 100, "status": "filled",
        "link_id": "L-AAA", "entry_price": 10.0,
        "entry_timestamp": "2026-07-10T14:00:00Z",
        "recorded_exposure": 1000.0,
        "child_order_ids": {"target": "", "stop": ""},
    }


@pytest.fixture(autouse=True)
def _fast_cancel_verify(monkeypatch):
    monkeypatch.setattr(v2, "_CANCEL_VERIFY_ATTEMPTS", 2)
    monkeypatch.setattr(v2, "_CANCEL_VERIFY_SLEEP_S", 0.0)


def test_exit_coid_deterministic_and_increments_on_confirmed_failure(tmp_path):
    cfg = _exit_cfg(tmp_path)
    pos = _exit_lot()
    oa_fake = SellOA()
    # Attempt 0: confirmed rejection (500), nothing at the broker.
    oa_fake.sell_responses = [{"_http_status": 500}]
    ok = v2.trigger_exit_v2(
        "AAA", pos, cfg, oa_client=oa_fake, api_key="k", http=None,
    )
    assert ok is False
    assert oa_fake.sells[0]["client_order_id"] == "L-AAA-EXIT0"
    assert pos["exit_attempt"] == 1        # coid burned by the reject
    assert pos["status"] == "filled"
    # Retry uses the NEXT deterministic id and succeeds.
    ok = v2.trigger_exit_v2(
        "AAA", pos, cfg, oa_client=oa_fake, api_key="k", http=None,
    )
    assert ok is True
    assert oa_fake.sells[1]["client_order_id"] == "L-AAA-EXIT1"
    assert pos["exit_client_order_id"] == "L-AAA-EXIT1"


def test_exit_exception_reuses_same_coid(tmp_path):
    cfg = _exit_cfg(tmp_path)
    pos = _exit_lot()

    class RaisingSellOA(SellOA):
        def __init__(self):
            super().__init__()
            self.raise_next = True

        def submit_market_sell(self, http, api_key, **kw):
            if self.raise_next:
                self.raise_next = False
                self.sells.append({"client_order_id":
                                    kw.get("client_order_id")})
                raise ConnectionError("timeout")
            return super().submit_market_sell(http, api_key, **kw)

    oa_fake = RaisingSellOA()
    ok = v2.trigger_exit_v2(
        "AAA", pos, cfg, oa_client=oa_fake, api_key="k", http=None,
    )
    assert ok is False
    assert pos.get("exit_attempt", 0) == 0   # NOT burned — outcome unknown
    ok = v2.trigger_exit_v2(
        "AAA", pos, cfg, oa_client=oa_fake, api_key="k", http=None,
    )
    assert ok is True
    # Both attempts used the SAME deterministic id.
    assert [s["client_order_id"] for s in oa_fake.sells] \
        == ["L-AAA-EXIT0", "L-AAA-EXIT0"]


def test_exit_rejection_adopts_existing_order_with_same_coid(tmp_path):
    """A duplicate-coid rejection means the earlier 'unknown' sell DID
    land — adopt it, never submit a second sell."""
    cfg = _exit_cfg(tmp_path)
    pos = _exit_lot()
    oa_fake = SellOA()
    oa_fake.sell_responses = [{"_http_status": 422}]  # duplicate coid
    oa_fake.rows = [{"id": "X-1", "client_order_id": "L-AAA-EXIT0",
                      "status": "new"}]
    ok = v2.trigger_exit_v2(
        "AAA", pos, cfg, oa_client=oa_fake, api_key="k", http=None,
    )
    assert ok is True
    assert pos["status"] == "exiting"
    assert pos["exit_order_id"] == "X-1"
    assert pos.get("exit_attempt", 0) == 0   # no increment on adoption
    assert len(oa_fake.sells) == 1            # no second sell
    assert any(e["event_type"] == "exit_adopted_existing"
               for e in _ledger_events(tmp_path))
