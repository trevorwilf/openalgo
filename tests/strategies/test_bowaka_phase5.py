"""Phase 5 — Post-closure rescreen + per-trigger telemetry.

Covers:
- ``entered_today`` same-day re-entry block in ``select_entries``
- ``remaining_entries_budget`` cap in ``select_entries``
- ``rescreen_pending`` flag set by closure events (target / stop / time_stop)
- ``signal_fade`` closures do NOT set the flag
- ``run_post_closure_rescreen`` is no-op when disabled / past cutoff / cap hit / kill switch on
- Successful rescreen submits entries with ``entry_trigger="post_closure_rescreen"``
- Daily entry cap counts across both open-tick and rescreen entries
- ``_past_last_entry_time`` fail-closes on bad config
- ``filter_by_intraday_confirmation`` honours ``band_override``
- ``reset_for_new_session`` clears all new daily fields
- ``write_session_summary`` includes ``by_trigger`` + rescreen counters
"""
from __future__ import annotations

import json
from datetime import date, datetime, timezone
from pathlib import Path

import httpx
import pytest


# ---------------------------------------------------------------- helpers


def _route(handlers):
    """Tiny MockTransport router. Keys are (method, path)."""
    def handler(req: httpx.Request) -> httpx.Response:
        key = (req.method, req.url.path)
        h = handlers.get(key)
        if h is None:
            return httpx.Response(404, json={"error": {"code": "no_route"}})
        if callable(h):
            return h(req)
        return h
    return httpx.MockTransport(handler)


def _candidates_payload(rows, *, as_of=None, config_hash="ph5-hash"):
    """Build a candidates JSON with today's NYSE date by default so the
    handshake passes regardless of when the test runs."""
    import pandas_market_calendars as mcal
    if as_of is None:
        nyse = mcal.get_calendar("NYSE")
        today = datetime.now(timezone.utc).date()
        sched = nyse.schedule(start_date=today.isoformat(),
                              end_date=today.isoformat())
        as_of = (today if not sched.empty else
                 nyse.schedule(
                     start_date=(today.replace(day=max(today.day - 5, 1))).isoformat(),
                     end_date=today.isoformat(),
                 ).index[-1].date()).isoformat()
    return {
        "as_of_date": as_of,
        "generated_at": as_of + "T20:30:00Z",
        "config_hash": config_hash,
        "n_universe_with_features": 5000,
        "n_passed_universe_gates": 800,
        "n_in_play": len(rows),
        "candidates": rows,
    }


def _row(ticker: str, close: float, signal: float, **extra) -> dict:
    base = {
        "ticker": ticker, "close": close,
        "rvol": 2.0, "atr_pct": 0.08, "range_expansion": 1.4,
        "gap_pct": 0.02, "close_location": 0.85,
        "ema_distance": 0.05, "ema_slope": 0.02,
        "avg_dollar_volume": 5_000_000.0,
        "signal_strength": signal,
        "venue_code": "XNAS", "exchange": "NASDAQ",
    }
    base.update(extra)
    return base


@pytest.fixture
def cfg_rescreen(cfg_with_paths):
    """cfg_with_paths + the rescreen + cap blocks Phase 5 introduces."""
    cfg = dict(cfg_with_paths)
    cfg["risk"] = {
        **cfg_with_paths["risk"],
        "max_position_as_adv_frac": 0.03,
        "max_total_entries_per_day": 10,
    }
    cfg["entry"] = {
        **cfg_with_paths.get("entry", {}),
        "bracket_pricing_mode": "actual_fill",
        "intraday_confirmation": {
            "enabled": True,
            "window_minutes": 0,
            "max_spread_pct": 0.05,
            "max_quote_age_seconds": 120,
            "price_band": {
                "max_pct_above_close": 0.30,
                "min_pct_below_close": -0.15,
            },
            "post_closure_price_band": {
                "max_pct_above_close": 0.10,
                "min_pct_below_close": -0.08,
            },
        },
        "post_closure_rescreen": {
            "enabled": True,
            "last_entry_time": "14:00",
            # Phase 3.2 — explicit opt-in to the reasons that should
            # set rescreen_pending. ``should_set_rescreen_pending``
            # fail-closes when ``only_after_reasons`` is missing, so
            # the legacy Phase 5 tests need this list to keep their
            # original target_hit / stop_hit / time_stop behavior
            # under test.
            "only_after_reasons": [
                "target_hit", "stop_hit", "time_stop",
            ],
        },
    }
    return cfg


def _filled_pos(*, qty=100, entry_price=10.0, target_id="T-1", stop_id="S-1",
                entry_trigger="session_open"):
    return {
        "parent_order_id": "P-1",
        "child_order_ids": {"target": target_id, "stop": stop_id},
        "qty": qty,
        "entry_price": entry_price,
        "entry_timestamp": "2026-05-04T13:30:00+00:00",
        "entry_features": {},
        "status": "filled",
        "venue_code": "XNAS",
        "target_price": entry_price * 1.15,
        "stop_price": entry_price * 0.92,
        "entry_trigger": entry_trigger,
    }


# ---------------------------------------------------------------- select_entries gates


def test_select_entries_skips_entered_today(strategy_module, cfg_rescreen):
    """Same-day re-entry block: a ticker in ``entered_today`` must not
    appear in a later select_entries result, even if open_positions is
    empty (i.e., it was entered earlier and has since closed)."""
    state = strategy_module.blank_state()
    state["entered_today"] = ["AAPL"]
    cands = [strategy_module.Candidate("AAPL", 10.0, 9.0)]
    selected = strategy_module.select_entries(
        cands, state, equity=100_000.0, latest_prices={},
        cfg=cfg_rescreen, kill_state=strategy_module.KillLevel.NONE,
    )
    assert selected == []


def test_select_entries_respects_remaining_budget(strategy_module, cfg_rescreen):
    """The rescreen passes ``remaining_entries_budget`` so the slate is
    capped against the daily total-entry budget."""
    state = strategy_module.blank_state()
    cands = [strategy_module.Candidate(f"T{i}", 10.0, 9.0 - i * 0.1) for i in range(5)]
    selected = strategy_module.select_entries(
        cands, state, equity=100_000.0, latest_prices={},
        cfg=cfg_rescreen, kill_state=strategy_module.KillLevel.NONE,
        remaining_entries_budget=2,
    )
    assert [e.ticker for e in selected] == ["T0", "T1"]


def test_select_entries_remaining_budget_zero_returns_empty(strategy_module, cfg_rescreen):
    """A zero budget short-circuits the selection."""
    state = strategy_module.blank_state()
    cands = [strategy_module.Candidate("AAPL", 10.0, 9.0)]
    selected = strategy_module.select_entries(
        cands, state, equity=100_000.0, latest_prices={},
        cfg=cfg_rescreen, kill_state=strategy_module.KillLevel.NONE,
        remaining_entries_budget=0,
    )
    assert selected == []


# ---------------------------------------------------------------- rescreen_pending flag


def test_target_fill_sets_rescreen_pending(strategy_module, cfg_rescreen, tmp_path):
    """Item: every intraday closure that frees capital must set
    rescreen_pending so the next tick can redeploy."""
    state = strategy_module.blank_state()
    state["open_positions"] = {"AAPL": _filled_pos()}
    summary_path = Path(cfg_rescreen["paths"]["daily_summary_path"])
    state_path = Path(cfg_rescreen["paths"]["state_path"])
    ev = strategy_module.FillEvent(
        ticker="AAPL", order_id="T-1", role="target", status="FILLED",
        filled_qty=100, filled_avg_price=11.50, raw={},
    )
    strategy_module.process_fill_events_for_closures(
        [ev], state, cfg_rescreen,
        state_path=state_path, summary_path=summary_path,
    )
    assert state.get("rescreen_pending") is True
    assert "AAPL" not in state["open_positions"]


def test_stop_fill_sets_rescreen_pending(strategy_module, cfg_rescreen, tmp_path):
    state = strategy_module.blank_state()
    state["open_positions"] = {"AAPL": _filled_pos()}
    state_path = Path(cfg_rescreen["paths"]["state_path"])
    summary_path = Path(cfg_rescreen["paths"]["daily_summary_path"])
    ev = strategy_module.FillEvent(
        ticker="AAPL", order_id="S-1", role="stop", status="FILLED",
        filled_qty=100, filled_avg_price=9.20, raw={},
    )
    strategy_module.process_fill_events_for_closures(
        [ev], state, cfg_rescreen,
        state_path=state_path, summary_path=summary_path,
    )
    assert state.get("rescreen_pending") is True


def test_signal_fade_fill_does_NOT_set_rescreen_pending(
    strategy_module, cfg_rescreen, tmp_path,
):
    """signal_fade fires at 16:05 ET, past the entry cutoff, and the
    name has just been signal-faded — there's no productive immediate
    re-entry. Keep the flag clear."""
    state = strategy_module.blank_state()
    pos = _filled_pos()
    pos["exit_reason"] = "signal_fade"
    state["open_positions"] = {"AAPL": pos}
    state_path = Path(cfg_rescreen["paths"]["state_path"])
    summary_path = Path(cfg_rescreen["paths"]["daily_summary_path"])
    ev = strategy_module.FillEvent(
        ticker="AAPL", order_id="EX-1", role="exit", status="FILLED",
        filled_qty=100, filled_avg_price=10.20, raw={},
    )
    strategy_module.process_fill_events_for_closures(
        [ev], state, cfg_rescreen,
        state_path=state_path, summary_path=summary_path,
    )
    assert state.get("rescreen_pending", False) is False


def test_time_stop_pass_sets_rescreen_pending(
    strategy_module, cfg_rescreen, tmp_path,
):
    """run_time_stop_pass sets the flag once when at least one ticker
    is time-stopped this pass."""
    state = strategy_module.blank_state()
    state["open_positions"] = {
        "AAPL": _filled_pos(qty=10, entry_price=10.0),
    }
    state["open_positions"]["AAPL"]["entry_timestamp"] = (
        "2026-05-04T13:30:00+00:00"  # >3 trading days behind 2026-05-11
    )
    state_path = Path(cfg_rescreen["paths"]["state_path"])
    routes = {
        # cancel + market sell happy path
        ("DELETE", "/api/v2/orders/T-1"): httpx.Response(200, json={"data": {}}),
        ("DELETE", "/api/v2/orders/S-1"): httpx.Response(200, json={"data": {}}),
        ("POST", "/api/v2/orders"): httpx.Response(200, json={
            "data": {"order_id": "EX-MOO-1", "native_response": {"id": "EX-MOO-1"}},
        }),
    }
    http = strategy_module.make_http_client("http://x", transport=_route(routes))
    triggered = strategy_module.run_time_stop_pass(
        cfg_rescreen, state, http, "k",
        today_et=date(2026, 5, 11), state_path=state_path,
    )
    assert triggered == ["AAPL"]
    assert state.get("rescreen_pending") is True


def test_multiple_closures_one_tick_set_one_flag(
    strategy_module, cfg_rescreen, tmp_path,
):
    """Debounce: three closure events in one tick set ``rescreen_pending``
    once (it's a bool). The post-closure rescreen reads the flag once
    at end-of-tick, runs once."""
    state = strategy_module.blank_state()
    state["open_positions"] = {
        "AAPL": _filled_pos(target_id="T-AAPL", stop_id="S-AAPL"),
        "MSFT": _filled_pos(target_id="T-MSFT", stop_id="S-MSFT"),
        "GME":  _filled_pos(target_id="T-GME",  stop_id="S-GME"),
    }
    state_path = Path(cfg_rescreen["paths"]["state_path"])
    summary_path = Path(cfg_rescreen["paths"]["daily_summary_path"])
    evs = [
        strategy_module.FillEvent(
            ticker="AAPL", order_id="T-AAPL", role="target", status="FILLED",
            filled_qty=100, filled_avg_price=11.50, raw={},
        ),
        strategy_module.FillEvent(
            ticker="MSFT", order_id="S-MSFT", role="stop", status="FILLED",
            filled_qty=100, filled_avg_price=9.20, raw={},
        ),
        strategy_module.FillEvent(
            ticker="GME", order_id="T-GME", role="target", status="FILLED",
            filled_qty=100, filled_avg_price=11.50, raw={},
        ),
    ]
    strategy_module.process_fill_events_for_closures(
        evs, state, cfg_rescreen,
        state_path=state_path, summary_path=summary_path,
    )
    # Single bool flag is the debounce mechanism — exactly the property
    # we want to pin here.
    assert state.get("rescreen_pending") is True
    assert state["open_positions"] == {}


# ---------------------------------------------------------------- run_post_closure_rescreen gates


def test_rescreen_noop_when_flag_clear(strategy_module, cfg_rescreen):
    state = strategy_module.blank_state()
    state["rescreen_pending"] = False
    state_path = Path(cfg_rescreen["paths"]["state_path"])
    http = strategy_module.make_http_client(
        "http://x", transport=_route({}),  # any HTTP call fails the test
    )
    n = strategy_module.run_post_closure_rescreen(
        cfg_rescreen, state, state_path, http, "k",
        today_et=date(2026, 5, 11),
        kill_state=strategy_module.KillLevel.NONE,
    )
    assert n == 0


def test_rescreen_noop_when_disabled_in_cfg(strategy_module, cfg_rescreen, tmp_path):
    """Operator turned the policy off via config — flag should be
    cleared but no entries submitted."""
    cfg = dict(cfg_rescreen)
    cfg["entry"] = {
        **cfg_rescreen["entry"],
        "post_closure_rescreen": {"enabled": False, "last_entry_time": "14:00"},
    }
    state = strategy_module.blank_state()
    state["rescreen_pending"] = True
    state_path = Path(cfg["paths"]["state_path"])
    http = strategy_module.make_http_client("http://x", transport=_route({}))
    n = strategy_module.run_post_closure_rescreen(
        cfg, state, state_path, http, "k",
        today_et=date(2026, 5, 11),
        kill_state=strategy_module.KillLevel.NONE,
    )
    assert n == 0
    assert state["rescreen_pending"] is False


def test_rescreen_noop_under_kill_switch(strategy_module, cfg_rescreen, tmp_path):
    state = strategy_module.blank_state()
    state["rescreen_pending"] = True
    state_path = Path(cfg_rescreen["paths"]["state_path"])
    http = strategy_module.make_http_client("http://x", transport=_route({}))
    n = strategy_module.run_post_closure_rescreen(
        cfg_rescreen, state, state_path, http, "k",
        today_et=date(2026, 5, 11),
        kill_state=strategy_module.KillLevel.L1_NEW,
    )
    assert n == 0
    assert state["rescreen_pending"] is False


def test_rescreen_noop_past_last_entry_time(
    strategy_module, cfg_rescreen, tmp_path, monkeypatch,
):
    """Walk-clock check: a 15:00 ET tick rejects entries even though
    the strategy session window runs to 15:55."""
    import pytz
    state = strategy_module.blank_state()
    state["rescreen_pending"] = True
    state_path = Path(cfg_rescreen["paths"]["state_path"])
    http = strategy_module.make_http_client("http://x", transport=_route({}))

    et = pytz.timezone("America/New_York")
    now_15_00_et = et.localize(
        datetime(2026, 5, 11, 15, 0, 0)
    ).astimezone(timezone.utc)
    n = strategy_module.run_post_closure_rescreen(
        cfg_rescreen, state, state_path, http, "k",
        today_et=date(2026, 5, 11),
        kill_state=strategy_module.KillLevel.NONE,
        now_utc=now_15_00_et,
    )
    assert n == 0
    assert state["rescreen_pending"] is False


def test_rescreen_noop_when_daily_cap_reached(
    strategy_module, cfg_rescreen, tmp_path,
):
    """daily_entries_count == cap → no new entries even with capacity."""
    state = strategy_module.blank_state()
    state["rescreen_pending"] = True
    state["daily_entries_count"] = 10  # equal to risk.max_total_entries_per_day
    state_path = Path(cfg_rescreen["paths"]["state_path"])
    http = strategy_module.make_http_client("http://x", transport=_route({}))
    n = strategy_module.run_post_closure_rescreen(
        cfg_rescreen, state, state_path, http, "k",
        today_et=date(2026, 5, 11),
        kill_state=strategy_module.KillLevel.NONE,
    )
    assert n == 0
    assert state["rescreen_pending"] is False


def test_past_last_entry_time_fail_closed_on_bad_format(strategy_module, cfg_rescreen):
    """A typo in the cutoff must NOT silently allow late entries."""
    import pytz
    et = pytz.timezone("America/New_York")
    now_10_00_et = et.localize(datetime(2026, 5, 11, 10, 0, 0)).astimezone(timezone.utc)
    assert strategy_module._past_last_entry_time(
        now_10_00_et, date(2026, 5, 11), "fourteen-o-clock", cfg_rescreen,
    ) is True


# ---------------------------------------------------------------- successful rescreen


def _balances(equity=100_000.0):
    def h(req):
        return httpx.Response(200, json={"data": {"balance": {
            "cash": str(equity), "equity": str(equity),
            "buying_power": str(equity * 2), "currency": "USD",
        }}})
    return h


def _orders_post_handler(parent_id="P-NEW"):
    """Accepts the parent MARKET BUY (actual_fill mode)."""
    def h(req):
        return httpx.Response(200, json={"data": {
            "order_id": parent_id,
            "native_response": {"id": parent_id, "status": "new"},
        }})
    return h


def _quotes_handler(price=10.0, *, price_by_ticker: dict[str, float] | None = None):
    """Return a quote with mid ≈ ``price`` (or per-ticker via map) so
    callers can simulate live quotes that pass intraday confirmation.
    The handler responds to /api/v2/quotes batched requests."""
    def h(req):
        try:
            body = json.loads(req.content)
        except Exception:
            body = {}
        rows = []
        for inst in body.get("instruments", []):
            sym = inst.get("canonical_symbol")
            p = (price_by_ticker or {}).get(sym, price)
            rows.append({
                "instrument": inst,
                "quote": {
                    "bid": p * 0.999, "ask": p * 1.001,
                    "last": p,
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                },
            })
        return httpx.Response(200, json={"data": rows})
    return h


def test_rescreen_submits_entries_when_conditions_pass(
    strategy_module, cfg_rescreen, tmp_path,
):
    """Happy path: pending flag, no open positions, candidates valid,
    intraday confirmation enabled, conditions all pass → entries
    submitted, counters incremented, flag cleared."""
    cands = [_row("AAPL", 10.0, 9.0), _row("MSFT", 12.0, 8.5)]
    Path(cfg_rescreen["paths"]["candidates_path"]).write_text(
        json.dumps(_candidates_payload(cands))
    )
    state = strategy_module.blank_state()
    state["rescreen_pending"] = True
    state["session_date"] = date.today().isoformat()
    state_path = Path(cfg_rescreen["paths"]["state_path"])
    routes = {
        ("GET", "/api/v2/balances"): _balances(),
        # Live mid sits at the candidate close → passes intraday
        # confirmation for both names.
        ("POST", "/api/v2/quotes"): _quotes_handler(
            price_by_ticker={"AAPL": 10.0, "MSFT": 12.0},
        ),
        ("POST", "/api/v2/orders"): _orders_post_handler(),
    }
    http = strategy_module.make_http_client("http://x", transport=_route(routes))
    import pytz
    et = pytz.timezone("America/New_York")
    now_10_30_et = et.localize(datetime(
        date.today().year, date.today().month, date.today().day,
        10, 30, 0,
    )).astimezone(timezone.utc)
    nyse_today = date.today()
    # Recover NYSE today (the candidates payload helper does the same).
    import pandas_market_calendars as mcal
    nyse = mcal.get_calendar("NYSE")
    sched = nyse.schedule(
        start_date=(nyse_today.replace(day=max(nyse_today.day - 5, 1))).isoformat(),
        end_date=nyse_today.isoformat(),
    )
    nyse_today = sched.index[-1].date()

    n = strategy_module.run_post_closure_rescreen(
        cfg_rescreen, state, state_path, http, "k",
        today_et=nyse_today,
        kill_state=strategy_module.KillLevel.NONE,
        now_utc=now_10_30_et,
    )
    assert n == 2
    assert state["rescreen_pending"] is False
    assert state["rescreens_today"] == 1
    assert state["post_closure_entries_today"] == 2
    assert state["daily_entries_count"] == 2
    assert sorted(state["entered_today"]) == ["AAPL", "MSFT"]
    # Each tagged with post_closure_rescreen on the position record.
    for ticker in ("AAPL", "MSFT"):
        assert state["open_positions"][ticker]["entry_trigger"] == "post_closure_rescreen"


def test_rescreen_increments_rescreens_today_even_when_zero_entries(
    strategy_module, cfg_rescreen, tmp_path,
):
    """The flag transition is a real rescreen attempt — count it even
    if the slate came back empty (e.g., every candidate failed
    intraday confirmation). Otherwise the operator can't tell whether
    the strategy didn't get a chance vs. tried-but-rejected."""
    cands = [_row("AAPL", 10.0, 9.0)]
    Path(cfg_rescreen["paths"]["candidates_path"]).write_text(
        json.dumps(_candidates_payload(cands))
    )
    state = strategy_module.blank_state()
    state["rescreen_pending"] = True
    # Pre-mark AAPL as already entered → dedup blocks it
    state["entered_today"] = ["AAPL"]
    state_path = Path(cfg_rescreen["paths"]["state_path"])
    routes = {
        ("GET", "/api/v2/balances"): _balances(),
        ("POST", "/api/v2/quotes"): _quotes_handler(price=10.0),
    }
    http = strategy_module.make_http_client("http://x", transport=_route(routes))

    import pandas_market_calendars as mcal
    import pytz
    nyse = mcal.get_calendar("NYSE")
    today = datetime.now(timezone.utc).date()
    sched = nyse.schedule(
        start_date=(today.replace(day=max(today.day - 5, 1))).isoformat(),
        end_date=today.isoformat(),
    )
    nyse_today = sched.index[-1].date()
    et = pytz.timezone("America/New_York")
    now_10_30_et = et.localize(datetime(
        nyse_today.year, nyse_today.month, nyse_today.day, 10, 30, 0,
    )).astimezone(timezone.utc)

    n = strategy_module.run_post_closure_rescreen(
        cfg_rescreen, state, state_path, http, "k",
        today_et=nyse_today,
        kill_state=strategy_module.KillLevel.NONE,
        now_utc=now_10_30_et,
    )
    assert n == 0
    assert state["rescreens_today"] == 1
    assert state["rescreen_pending"] is False
    assert state["post_closure_entries_today"] == 0


def test_rescreen_does_not_clear_flag_on_equity_fetch_failure(
    strategy_module, cfg_rescreen, tmp_path,
):
    """Transient broker error: the flag must persist so the next tick
    retries. Otherwise a 5-second balances hiccup costs us the whole
    rescreen for that closure event."""
    import pytz
    state = strategy_module.blank_state()
    state["rescreen_pending"] = True
    state_path = Path(cfg_rescreen["paths"]["state_path"])
    routes = {
        ("GET", "/api/v2/balances"): httpx.Response(502, json={"error": "transient"}),
    }
    http = strategy_module.make_http_client("http://x", transport=_route(routes))
    et = pytz.timezone("America/New_York")
    now_10_30_et = et.localize(
        datetime(2026, 5, 11, 10, 30, 0)
    ).astimezone(timezone.utc)
    n = strategy_module.run_post_closure_rescreen(
        cfg_rescreen, state, state_path, http, "k",
        today_et=date(2026, 5, 11),
        kill_state=strategy_module.KillLevel.NONE,
        now_utc=now_10_30_et,
    )
    assert n == 0
    # Flag retained → next tick retries.
    assert state.get("rescreen_pending") is True


def test_rescreen_honors_max_total_entries_per_day_across_open_and_rescreen(
    strategy_module, cfg_rescreen, tmp_path,
):
    """A 10-entry cap with 9 already submitted means only ONE more
    entry can come from the rescreen, even if 5 candidates qualify."""
    cfg = dict(cfg_rescreen)
    cfg["risk"] = {**cfg["risk"], "max_total_entries_per_day": 10}
    cands = [_row(f"T{i}", 10.0, 9.0 - i * 0.1) for i in range(5)]
    Path(cfg["paths"]["candidates_path"]).write_text(
        json.dumps(_candidates_payload(cands))
    )
    state = strategy_module.blank_state()
    state["rescreen_pending"] = True
    state["daily_entries_count"] = 9  # one slot left
    state_path = Path(cfg["paths"]["state_path"])
    routes = {
        ("GET", "/api/v2/balances"): _balances(),
        ("POST", "/api/v2/quotes"): _quotes_handler(price=10.0),
        ("POST", "/api/v2/orders"): _orders_post_handler(),
    }
    http = strategy_module.make_http_client("http://x", transport=_route(routes))

    import pandas_market_calendars as mcal
    import pytz
    nyse = mcal.get_calendar("NYSE")
    today = datetime.now(timezone.utc).date()
    sched = nyse.schedule(
        start_date=(today.replace(day=max(today.day - 5, 1))).isoformat(),
        end_date=today.isoformat(),
    )
    nyse_today = sched.index[-1].date()
    et = pytz.timezone("America/New_York")
    now_10_30_et = et.localize(datetime(
        nyse_today.year, nyse_today.month, nyse_today.day, 10, 30, 0,
    )).astimezone(timezone.utc)

    n = strategy_module.run_post_closure_rescreen(
        cfg, state, state_path, http, "k",
        today_et=nyse_today,
        kill_state=strategy_module.KillLevel.NONE,
        now_utc=now_10_30_et,
    )
    assert n == 1
    assert state["daily_entries_count"] == 10


# ---------------------------------------------------------------- intraday confirmation band override


def test_intraday_confirmation_band_override_rejects_more(
    strategy_module, cfg_rescreen,
):
    """A name 15% above yesterday's close PASSES the open-tick band
    (max_pct_above_close=0.30) but FAILS the tighter post-closure
    band (max_pct_above_close=0.10)."""
    Entry = strategy_module.Entry
    Candidate = strategy_module.Candidate
    cand = Candidate("AAPL", 10.0, 9.0)
    entry = Entry(
        ticker="AAPL", qty=100, close_price=10.0,
        venue_code="XNAS", candidate=cand, equity_at_entry=100_000.0,
    )
    # Live mid is 11.50 → +15% above candidate.close.
    def quote_h(req):
        return httpx.Response(200, json={"data": [{
            "instrument": {"canonical_symbol": "AAPL", "venue_code": "XNAS"},
            "quote": {
                "bid": 11.45, "ask": 11.55, "last": 11.50,
                "timestamp": datetime.now(timezone.utc).isoformat(),
            },
        }]})
    http = strategy_module.make_http_client("http://x", transport=_route({
        ("POST", "/api/v2/quotes"): quote_h,
    }))

    # Open-tick band: passes (15% < 30%).
    out_open = strategy_module.filter_by_intraday_confirmation(
        [entry], cfg_rescreen, http, "k",
    )
    assert [e.ticker for e in out_open] == ["AAPL"]

    # Post-closure band: rejected (15% > 10%).
    out_rescreen = strategy_module.filter_by_intraday_confirmation(
        [entry], cfg_rescreen, http, "k",
        band_override=cfg_rescreen["entry"]["intraday_confirmation"][
            "post_closure_price_band"
        ],
    )
    assert out_rescreen == []


# ---------------------------------------------------------------- state lifecycle


def test_reset_for_new_session_clears_phase5_fields(strategy_module):
    state = strategy_module.blank_state()
    state["entered_today"] = ["AAPL", "MSFT"]
    state["daily_entries_count"] = 7
    state["rescreen_pending"] = True
    state["rescreens_today"] = 3
    state["post_closure_entries_today"] = 4
    strategy_module.reset_for_new_session(state, "2026-05-12", 110_000.0)
    assert state["entered_today"] == []
    assert state["daily_entries_count"] == 0
    assert state["rescreen_pending"] is False
    assert state["rescreens_today"] == 0
    assert state["post_closure_entries_today"] == 0
    assert state["session_date"] == "2026-05-12"


# ---------------------------------------------------------------- closure records


def test_closure_record_carries_entry_trigger(
    strategy_module, cfg_rescreen, tmp_path,
):
    """The closure record gets ``entry_trigger`` from the position
    record so post-trade analysis can split open-tick from rescreen
    trades by realized PnL."""
    state = strategy_module.blank_state()
    state["open_positions"] = {
        "AAPL": _filled_pos(entry_trigger="post_closure_rescreen"),
    }
    summary_path = Path(cfg_rescreen["paths"]["daily_summary_path"])
    state_path = Path(cfg_rescreen["paths"]["state_path"])
    rec = strategy_module.close_position(
        "AAPL", state, cfg_rescreen,
        state_path=state_path, summary_path=summary_path,
        exit_price=11.50, reason="target_hit",
    )
    assert rec["entry_trigger"] == "post_closure_rescreen"


def test_opened_record_carries_entry_trigger(
    strategy_module, cfg_rescreen, tmp_path,
):
    state = strategy_module.blank_state()
    state["open_positions"] = {
        "AAPL": {
            **_filled_pos(entry_trigger="post_closure_rescreen"),
            "status": "pending_fill",
        },
    }
    summary_path = Path(cfg_rescreen["paths"]["daily_summary_path"])
    state_path = Path(cfg_rescreen["paths"]["state_path"])
    ev = strategy_module.FillEvent(
        ticker="AAPL", order_id="P-1", role="parent", status="FILLED",
        filled_qty=100, filled_avg_price=10.05, raw={},
    )
    strategy_module.process_fill_events_for_closures(
        [ev], state, cfg_rescreen,
        state_path=state_path, summary_path=summary_path,
    )
    # Walk the jsonl for the opened record.
    opened = [
        json.loads(line)
        for line in summary_path.read_text().splitlines()
        if line.strip() and json.loads(line).get("record_type") == "opened"
    ]
    assert opened
    assert opened[-1]["entry_trigger"] == "post_closure_rescreen"


# ---------------------------------------------------------------- session summary


def test_session_summary_includes_by_trigger_and_counters(
    strategy_module, cfg_rescreen, tmp_path,
):
    summary_path = Path(cfg_rescreen["paths"]["daily_summary_path"])
    state_path = Path(cfg_rescreen["paths"]["state_path"])
    today = "2026-05-11"
    # Build a tiny ledger: 2 open-tick opens, 1 rescreen open, 1
    # rescreen closure (loss), 1 open-tick closure (win).
    records = [
        {"record_type": "opened", "ticker": "A", "entry_timestamp": today + "T13:30:00Z",
         "entry_trigger": "session_open"},
        {"record_type": "opened", "ticker": "B", "entry_timestamp": today + "T13:30:01Z",
         "entry_trigger": "session_open"},
        {"record_type": "opened", "ticker": "C", "entry_timestamp": today + "T15:30:00Z",
         "entry_trigger": "post_closure_rescreen"},
        {"record_type": "closure", "ticker": "A", "exit_timestamp": today + "T14:00:00Z",
         "realized_pnl": 250.0, "reason": "target_hit",
         "entry_trigger": "session_open"},
        {"record_type": "closure", "ticker": "C", "exit_timestamp": today + "T15:50:00Z",
         "realized_pnl": -75.0, "reason": "stop_hit",
         "entry_trigger": "post_closure_rescreen"},
    ]
    summary_path.write_text("\n".join(json.dumps(r) for r in records) + "\n")
    # Phase 1.6: write_session_summary now reads the canonical trade
    # ledger (sibling file). Seed equivalent events so the assertions
    # below continue to reflect the same scenario.
    import uuid
    ledger_path = summary_path.parent / "trade_ledger.jsonl"
    ledger_events = [
        # Parent fills (session_open) — A and B
        {"event_type": "order_fill", "session_date": today, "trade_id": "BOWAKA-A-1",
         "ticker": "A", "role": "parent",
         "payload": {"entry_trigger": "session_open"}},
        {"event_type": "order_fill", "session_date": today, "trade_id": "BOWAKA-B-1",
         "ticker": "B", "role": "parent",
         "payload": {"entry_trigger": "session_open"}},
        # Parent fill (rescreen) — C
        {"event_type": "order_fill", "session_date": today, "trade_id": "BOWAKA-C-1",
         "ticker": "C", "role": "parent",
         "payload": {"entry_trigger": "post_closure_rescreen"}},
        # Closures
        {"event_type": "closure", "session_date": today, "trade_id": "BOWAKA-A-1",
         "ticker": "A",
         "payload": {"realized_pnl": 250.0, "reason": "target_hit",
                     "entry_trigger": "session_open"}},
        {"event_type": "closure", "session_date": today, "trade_id": "BOWAKA-C-1",
         "ticker": "C",
         "payload": {"realized_pnl": -75.0, "reason": "stop_hit",
                     "entry_trigger": "post_closure_rescreen"}},
    ]
    with open(ledger_path, "a", encoding="utf-8") as f:
        for raw in ledger_events:
            ev = {
                "schema_version": 1, "event_id": uuid.uuid4().hex,
                "ts": today + "T13:30:00+00:00",
                **raw,
            }
            f.write(json.dumps(ev) + "\n")

    state = strategy_module.blank_state()
    state["rescreens_today"] = 2
    state["post_closure_entries_today"] = 1
    rec = strategy_module.write_session_summary(
        state, cfg_rescreen,
        summary_path=summary_path, state_path=state_path,
        today_iso=today,
    )
    assert rec is not None
    assert rec["count_opened"] == 3
    assert rec["count_closed"] == 2
    assert rec["total_realized_pnl"] == pytest.approx(175.0)
    assert rec["rescreens_today"] == 2
    assert rec["post_closure_entries_today"] == 1
    assert rec["by_trigger"]["session_open"] == {
        "opened": 2, "closed": 1, "realized_pnl": 250.0,
    }
    assert rec["by_trigger"]["post_closure_rescreen"] == {
        "opened": 1, "closed": 1, "realized_pnl": -75.0,
    }
