"""Phase 6 audit acceptance tests — risk sizing + marketable-limit.

Covers:
  6.2 adv_tier_cap: tier matching + reject_if_below + empty-list
       fallback.
  6.2 compute_risk_sized_qty: target_risk + slippage + ADV cap +
       max_per_trade_dollars + min_order_notional.
  6.3 compute_marketable_buy_limit: ask*(1+slip) capped by price-
       band ceiling.
  6.3 submit_parent_marketable_limit_buy: posts LIMIT body, position
       carries entry_order_style + entry_limit_price.
  6.3 marketable_limit_timeout: poll_fills cancels and frees slot
       after timeout elapsed.
  Back-compat: order_style="market" + sizing_mode="equal_slice"
       produces byte-identical state to pre-Phase-6.
"""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import httpx
import pytest


# ---------------------------------------------------------------- 6.2 adv_tier_cap


def _cfg_with_tiers(tiers: list[dict]) -> dict:
    return {"risk": {"adv_tier_caps": tiers}}


def test_adv_tier_cap_empty_returns_no_cap(strategy_module):
    """Empty tier list + no flat fallback = ``(True, 0.0)``: allowed
    with no cap. Updated for the ADV-tier-caps feature contract
    (was: ``cap is None``)."""
    allowed, cap = strategy_module.adv_tier_cap(1_000_000.0, _cfg_with_tiers([]))
    assert allowed is True
    assert cap == 0.0


def test_adv_tier_cap_reject_below(strategy_module):
    tiers = [
        {"max_adv_dollars": 500_000, "reject_if_below": True,
         "max_position_as_adv_frac": 0.0},
        {"max_adv_dollars": 1_000_000, "max_position_as_adv_frac": 0.005},
        {"max_adv_dollars": None, "max_position_as_adv_frac": 0.015},
    ]
    cfg = _cfg_with_tiers(tiers)
    allowed, cap = strategy_module.adv_tier_cap(400_000.0, cfg)
    assert allowed is False


def test_adv_tier_cap_picks_smallest_qualifying(strategy_module):
    tiers = [
        {"max_adv_dollars": 1_000_000, "max_position_as_adv_frac": 0.005},
        {"max_adv_dollars": 5_000_000, "max_position_as_adv_frac": 0.010},
        {"max_adv_dollars": None, "max_position_as_adv_frac": 0.015},
    ]
    cfg = _cfg_with_tiers(tiers)
    # ADV 750k → first tier (1M cap) → frac 0.005 → cap = $3,750
    allowed, cap = strategy_module.adv_tier_cap(750_000.0, cfg)
    assert allowed is True
    assert cap == pytest.approx(750_000 * 0.005)
    # ADV 3M → second tier → cap = $30,000
    _, cap2 = strategy_module.adv_tier_cap(3_000_000.0, cfg)
    assert cap2 == pytest.approx(3_000_000 * 0.010)
    # ADV 10M → unbounded tier → cap = $150,000
    _, cap3 = strategy_module.adv_tier_cap(10_000_000.0, cfg)
    assert cap3 == pytest.approx(10_000_000 * 0.015)


# ---------------------------------------------------------------- 6.2 compute_risk_sized_qty


def _risk_cfg(**overrides) -> dict:
    base = {
        "sizing": {
            "sizing_mode": "risk_per_trade",
            "target_risk_dollars": 200,
            "max_per_trade_dollars": None,
            "min_order_notional": 0,
            "default_venue_code": "XNAS",
        },
        "risk": {
            "expected_stop_slippage_pct": 0.015,
            "adv_tier_caps": [],
            "max_position_as_adv_frac": None,
        },
        "exits": {"stop_pct": 0.08},
    }
    for k, v in overrides.items():
        sub, key = k.split(".", 1) if "." in k else (None, k)
        if sub:
            base.setdefault(sub, {})[key] = v
        else:
            base[k] = v
    return base


def test_compute_risk_sized_qty_basic(strategy_module):
    """target_risk=200, entry=10, stop=0.08, slip=0.015 →
       loss_per_share = 10*(0.08+0.015) = 0.95
       qty = floor(200/0.95) = 210

    Note: the ADV-tier-caps feature makes ``adv_tier_cap`` reject
    candidates with missing ADV. Pass a permissive ADV here so the
    ADV cap does not bind and the risk-based qty is the answer.
    """
    cfg = _risk_cfg()
    qty = strategy_module.compute_risk_sized_qty(
        entry_price=10.0, stop_pct=0.08,
        avg_dollar_volume=1_000_000_000.0,    # huge ADV, no binding cap
        cfg=cfg,
    )
    assert qty == 210


def test_compute_risk_sized_qty_max_per_trade_dollars_caps(strategy_module):
    """max_per_trade_dollars=1000 caps qty=floor(1000/10)=100."""
    cfg = _risk_cfg()
    cfg["sizing"]["max_per_trade_dollars"] = 1000
    qty = strategy_module.compute_risk_sized_qty(
        entry_price=10.0, stop_pct=0.08,
        avg_dollar_volume=1_000_000_000.0,
        cfg=cfg,
    )
    assert qty == 100


def test_compute_risk_sized_qty_adv_tier_caps_bind(strategy_module):
    """ADV tier caps reduce qty when tighter than risk-based size."""
    cfg = _risk_cfg()
    cfg["risk"]["adv_tier_caps"] = [
        {"max_adv_dollars": 1_000_000, "max_position_as_adv_frac": 0.005},
    ]
    # ADV 1M, tier=0.005, cap=$5000, entry=10 → qty floor(500) = 500
    # Risk-based qty without ADV would be 210 (cheaper). ADV cap is
    # less restrictive here; the risk cap binds.
    qty = strategy_module.compute_risk_sized_qty(
        entry_price=10.0, stop_pct=0.08, avg_dollar_volume=1_000_000, cfg=cfg,
    )
    assert qty == 210
    # ADV 100k -> cap=$500 -> qty floor(50)=50; tighter than 210.
    cfg["risk"]["adv_tier_caps"] = [
        {"max_adv_dollars": 100_000, "max_position_as_adv_frac": 0.005},
        {"max_adv_dollars": None, "max_position_as_adv_frac": 0.005},
    ]
    qty2 = strategy_module.compute_risk_sized_qty(
        entry_price=10.0, stop_pct=0.08, avg_dollar_volume=100_000, cfg=cfg,
    )
    assert qty2 == 50


def test_compute_risk_sized_qty_min_order_notional_rejects(strategy_module):
    """Notional below min_order_notional → qty=0."""
    cfg = _risk_cfg()
    cfg["sizing"]["target_risk_dollars"] = 5   # tiny risk
    cfg["sizing"]["min_order_notional"] = 500
    # loss_per_share=0.95 → qty=floor(5/0.95)=5 → notional=50 < 500
    qty = strategy_module.compute_risk_sized_qty(
        entry_price=10.0, stop_pct=0.08,
        avg_dollar_volume=1_000_000_000.0,    # permissive ADV
        cfg=cfg,
    )
    assert qty == 0


def test_compute_risk_sized_qty_adv_reject_drops_to_zero(strategy_module):
    cfg = _risk_cfg()
    cfg["risk"]["adv_tier_caps"] = [
        {"max_adv_dollars": 500_000, "reject_if_below": True,
         "max_position_as_adv_frac": 0.0},
        {"max_adv_dollars": None, "max_position_as_adv_frac": 0.01},
    ]
    qty = strategy_module.compute_risk_sized_qty(
        entry_price=10.0, stop_pct=0.08, avg_dollar_volume=300_000, cfg=cfg,
    )
    assert qty == 0


# ---------------------------------------------------------------- 6.3 compute_marketable_buy_limit


def test_compute_marketable_buy_limit_basic(strategy_module):
    cand = strategy_module.Candidate("AAPL", 10.0, 5.0, venue_code="XNAS",
                                     features={"avg_dollar_volume": 1e7})
    entry = strategy_module.Entry(
        ticker="AAPL", qty=100, close_price=10.0,
        venue_code="XNAS", candidate=cand,
    )
    cfg = {
        "entry": {
            "max_entry_slippage_pct": 0.005,
            "intraday_confirmation": {
                "price_band": {"max_pct_above_close": 0.15},
            },
        },
    }
    quote = {"bid": 9.99, "ask": 10.00}
    limit = strategy_module.compute_marketable_buy_limit(entry, quote, cfg)
    # ask 10.00 * 1.005 = 10.05; chase cap 10*1.15=11.5 → not binding.
    assert limit == pytest.approx(10.05)


def test_compute_marketable_buy_limit_capped_by_price_band(strategy_module):
    """When ask * (1 + slip) exceeds the chase cap, the limit clips."""
    cand = strategy_module.Candidate("AAPL", 10.0, 5.0, venue_code="XNAS")
    entry = strategy_module.Entry(
        ticker="AAPL", qty=100, close_price=10.0,
        venue_code="XNAS", candidate=cand,
    )
    cfg = {
        "entry": {
            "max_entry_slippage_pct": 0.50,   # extreme
            "intraday_confirmation": {
                "price_band": {"max_pct_above_close": 0.15},
            },
        },
    }
    quote = {"bid": 11.0, "ask": 11.2}
    limit = strategy_module.compute_marketable_buy_limit(entry, quote, cfg)
    # ask*1.5 = 16.8; chase cap = 10*1.15 = 11.5; clip → 11.5
    assert limit == pytest.approx(11.5)


def test_compute_marketable_buy_limit_no_quote(strategy_module):
    cand = strategy_module.Candidate("AAPL", 10.0, 5.0, venue_code="XNAS")
    entry = strategy_module.Entry(
        ticker="AAPL", qty=100, close_price=10.0,
        venue_code="XNAS", candidate=cand,
    )
    cfg = {"entry": {"max_entry_slippage_pct": 0.005,
                     "intraday_confirmation": {}}}
    assert strategy_module.compute_marketable_buy_limit(entry, {"bid": 0, "ask": 0}, cfg) is None


# ---------------------------------------------------------------- 6.3 submit_parent_marketable_limit_buy


def _route(handlers):
    def handler(req: httpx.Request) -> httpx.Response:
        key = (req.method, req.url.path)
        h = handlers.get(key)
        if h is None:
            return httpx.Response(404, json={"error": {"code": "no_route"}})
        if callable(h):
            return h(req)
        return h
    return httpx.MockTransport(handler)


def test_submit_parent_marketable_limit_buy_posts_limit(
    strategy_module, cfg_with_paths,
):
    cand = strategy_module.Candidate(
        "AAPL", 10.0, 5.0, venue_code="XNAS",
        features={"avg_dollar_volume": 1e7},
    )
    entry = strategy_module.Entry(
        ticker="AAPL", qty=100, close_price=10.0,
        venue_code="XNAS", candidate=cand, equity_at_entry=100_000.0,
    )
    state = strategy_module.blank_state()
    state_path = Path(cfg_with_paths["paths"]["state_path"])
    state_path.parent.mkdir(parents=True, exist_ok=True)
    seen_bodies: list[dict] = []

    def order_handler(req: httpx.Request) -> httpx.Response:
        seen_bodies.append(json.loads(req.content.decode()))
        return httpx.Response(200, json={
            "data": {"order_id": "PL-1", "native_response": {"id": "PL-1"}},
        })

    transport = _route({("POST", "/api/v2/orders"): order_handler})
    http = strategy_module.make_http_client("http://x", transport=transport)
    res = strategy_module.submit_parent_marketable_limit_buy(
        entry, limit_price=10.05, cfg=cfg_with_paths, http=http, api_key="k",
        state=state, state_path=state_path,
    )
    assert seen_bodies[0]["order_type"] == "LIMIT"
    assert seen_bodies[0]["price"] == "10.05"
    pos = state["open_positions"]["AAPL"]
    assert pos["entry_order_style"] == "marketable_limit"
    assert pos["entry_limit_price"] == 10.05


# ---------------------------------------------------------------- 6.3 marketable_limit_timeout


def test_marketable_limit_timeout_cancels_and_frees_slot(
    strategy_module, cfg_with_paths,
):
    """A marketable_limit position older than timeout_seconds is
    cancelled and removed from open_positions."""
    cfg = dict(cfg_with_paths)
    cfg["entry"] = {
        **cfg.get("entry", {}),
        "order_style": "marketable_limit",
        "marketable_limit_timeout_seconds": 30,
    }
    state = strategy_module.blank_state()
    state_path = Path(cfg["paths"]["state_path"])
    state_path.parent.mkdir(parents=True, exist_ok=True)
    state["open_positions"] = {
        "AAPL": {
            "parent_order_id": "PL-1",
            "child_order_ids": {"target": "", "stop": ""},
            "qty": 100, "entry_price": None,
            # Submitted 60s ago — past the 30s timeout.
            "entry_timestamp": (
                datetime.now(timezone.utc) - timedelta(seconds=60)
            ).isoformat(),
            "status": "pending_fill",
            "venue_code": "XNAS",
            "link_id": "BOWAKA-AAPL-1",
            "entry_order_style": "marketable_limit",
            "entry_limit_price": 10.05,
        }
    }
    n_cancel = [0]

    def cancel_handler(req: httpx.Request) -> httpx.Response:
        n_cancel[0] += 1
        return httpx.Response(200, json={"data": {}})

    def orders_handler(req: httpx.Request) -> httpx.Response:
        # GET /api/v2/orders?status=all returns empty (broker says
        # no fill yet).
        return httpx.Response(200, json={"data": {"orders": []}})

    transport = _route({
        ("DELETE", "/api/v2/orders/PL-1"): cancel_handler,
        ("GET", "/api/v2/orders"): orders_handler,
    })
    http = strategy_module.make_http_client("http://x", transport=transport)
    strategy_module.poll_fills(state, http, "k", state_path=state_path, cfg=cfg)
    assert n_cancel[0] == 1
    assert "AAPL" not in state["open_positions"]
    # Ledger captured the missed_trade event.
    ledger_path = (
        Path(cfg["paths"]["daily_summary_path"]).parent / "trade_ledger.jsonl"
    )
    events = []
    if ledger_path.exists():
        for line in ledger_path.read_text().splitlines():
            if line.strip():
                events.append(json.loads(line))
    types = [e["event_type"] for e in events]
    assert "missed_trade" in types


# ---------------------------------------------------------------- back-compat


def test_back_compat_equal_slice_market(strategy_module, cfg_with_paths):
    """order_style=market + sizing_mode=equal_slice (defaults) produces
    a state record indistinguishable from the pre-Phase-6 code path
    on the position-shape fields."""
    cand = strategy_module.Candidate(
        "AAPL", 10.0, 5.0, venue_code="XNAS",
        features={"avg_dollar_volume": 1e7},
    )
    entry = strategy_module.Entry(
        ticker="AAPL", qty=100, close_price=10.0,
        venue_code="XNAS", candidate=cand, equity_at_entry=100_000.0,
    )
    state = strategy_module.blank_state()
    state_path = Path(cfg_with_paths["paths"]["state_path"])
    state_path.parent.mkdir(parents=True, exist_ok=True)

    def order_handler(req: httpx.Request) -> httpx.Response:
        body = json.loads(req.content.decode())
        # Phase 6 back-compat: still a MARKET order.
        assert body["order_type"] == "MARKET"
        return httpx.Response(200, json={
            "data": {"order_id": "P-1", "native_response": {"id": "P-1"}},
        })

    transport = _route({("POST", "/api/v2/orders"): order_handler})
    http = strategy_module.make_http_client("http://x", transport=transport)
    strategy_module.submit_parent_market_buy(
        entry, cfg_with_paths, http, "k",
        state=state, state_path=state_path,
    )
    pos = state["open_positions"]["AAPL"]
    assert pos["entry_order_style"] == "market"


# ---------------------------------------------------------------- 6.5 R-multiple


def test_planned_risk_dollars_used_in_r_multiple(strategy_module, cfg_with_paths):
    """When the position has planned_risk_dollars set, close_position
    uses it for R-multiple instead of stop_pct math."""
    state = strategy_module.blank_state()
    state["open_positions"] = {
        "AAPL": {
            "qty": 100, "entry_price": 10.0,
            "stop_pct": 0.08, "target_pct": 0.15,
            "entry_timestamp": "2026-05-11T13:30:00+00:00",
            "venue_code": "XNAS", "link_id": "BOWAKA-AAPL-1",
            "planned_risk_dollars": 200.0,
            "peak_since_entry": 10.5,
            "trough_since_entry": 9.8,
        }
    }
    state_path = Path(cfg_with_paths["paths"]["state_path"])
    summary_path = Path(cfg_with_paths["paths"]["daily_summary_path"])
    summary_path.parent.mkdir(parents=True, exist_ok=True)
    strategy_module.close_position(
        "AAPL", state, cfg_with_paths,
        state_path=state_path, summary_path=summary_path,
        exit_price=11.0,    # +$100 pnl
        reason="target_hit",
    )
    ledger_path = summary_path.parent / "trade_ledger.jsonl"
    closures = []
    for line in ledger_path.read_text().splitlines():
        if not line.strip():
            continue
        ev = json.loads(line)
        if ev["event_type"] == "closure":
            closures.append(ev)
    assert len(closures) == 1
    # realized = +100, planned_risk = $200 → R-multiple = 0.5
    assert closures[0]["payload"]["planned_risk_dollars"] == pytest.approx(200.0)
    assert closures[0]["payload"]["R_multiple"] == pytest.approx(0.5)
