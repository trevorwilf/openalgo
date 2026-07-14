"""Fix Phase 6 — calendar-aware time stops.

The time-stop window anchors to the venue's ACTUAL session close via
GET /api/v2/calendar/timings: holidays fire nothing, early closes
shift the window (13:00 close ⇒ 12:15–12:55), regular days match the
legacy window exactly, and a failed timings fetch falls back to the
legacy weekday + absolute-times behavior.
"""
from __future__ import annotations

import json

import httpx
import pandas as pd
import pytest

import bowaka_v2_openalgo_client as oa
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


@pytest.fixture(autouse=True)
def _clear_timings_cache(monkeypatch):
    monkeypatch.setattr(v2, "_SESSION_TIMINGS_CACHE", {})
    monkeypatch.setattr(v2, "_TIMINGS_LAST_ATTEMPT", {})


def _cfg(tmp_path):
    return {
        "paths": {
            "trade_ledger_path": str(tmp_path / "trade_ledger.jsonl"),
            "daily_summary_path": str(tmp_path / "daily_summary.jsonl"),
        },
        "execution": {"default_venue_code": "XNAS"},
        "session": {"end": "15:55"},
        "exits": {"stop_pct": 0.05, "target_pct": 0.10,
                  "max_hold_days": 2, "oco_time_in_force": "GTC",
                  "time_stop": {"enabled": True, "exit_time": "15:15"}},
        "logging": {"log_protection_state": True},
    }


def _et(s: str) -> pd.Timestamp:
    return pd.Timestamp(s, tz="America/New_York")


def _open_day(close_utc: str) -> dict:
    return {"is_open": True, "session_close": close_utc,
            "timezone": "America/New_York"}


# ---- window derivation ----------------------------------------------------------


def test_holiday_fires_nothing_even_in_legacy_window(tmp_path):
    cfg = _cfg(tmp_path)
    # A Thursday 15:20 ET — inside the legacy window — but a holiday.
    assert v2._in_time_stop_window(
        _et("2026-07-02 15:20"), cfg, {"is_open": False},
    ) is False


@pytest.mark.parametrize("now,inside", [
    ("2026-07-02 12:14", False),
    ("2026-07-02 12:15", True),
    ("2026-07-02 12:30", True),
    ("2026-07-02 12:55", True),
    ("2026-07-02 12:56", False),
    ("2026-07-02 15:20", False),   # legacy slot is PAST the early close
])
def test_early_close_shifts_window(tmp_path, now, inside):
    cfg = _cfg(tmp_path)
    # 2026-07-02 (EDT): 13:00 ET close = 17:00 UTC.
    timings = _open_day("2026-07-02T17:00:00+00:00")
    assert v2._in_time_stop_window(_et(now), cfg, timings) is inside


@pytest.mark.parametrize("now,inside", [
    ("2026-07-14 15:14", False),
    ("2026-07-14 15:15", True),
    ("2026-07-14 15:35", True),
    ("2026-07-14 15:55", True),
    ("2026-07-14 15:56", False),
])
def test_regular_day_matches_legacy_window(tmp_path, now, inside):
    cfg = _cfg(tmp_path)
    # Regular 16:00 ET close = 20:00 UTC (EDT).
    timings = _open_day("2026-07-14T20:00:00+00:00")
    assert v2._in_time_stop_window(_et(now), cfg, timings) is inside
    # And identical to the timings-less legacy computation.
    assert v2._in_time_stop_window(_et(now), cfg, None) is inside


def test_no_timings_keeps_legacy_behavior(tmp_path):
    cfg = _cfg(tmp_path)
    assert v2._in_time_stop_window(_et("2026-07-14 15:20"), cfg) is True
    # Saturday — legacy weekday guard.
    assert v2._in_time_stop_window(_et("2026-07-18 15:20"), cfg) is False


def test_unusable_close_falls_back_to_legacy(tmp_path):
    cfg = _cfg(tmp_path)
    timings = _open_day("not-a-timestamp")
    assert v2._in_time_stop_window(
        _et("2026-07-14 15:20"), cfg, timings,
    ) is True


# ---- pass-level behavior ----------------------------------------------------------


class ExitOA:
    def __init__(self, timings=None):
        self.timings = timings
        self.timings_calls: list[str] = []
        self.market_sells: list[dict] = []

    def fetch_calendar_timings(self, http, api_key, *, venue_code,
                                date_iso):
        self.timings_calls.append(date_iso)
        return self.timings

    def cancel_order(self, http, api_key, order_id):
        return {"status": "canceled", "order_id": order_id}

    def fetch_order(self, http, api_key, order_id):
        return {"id": order_id, "status": "canceled", "filled_qty": 0}

    def fetch_all_orders(self, http, api_key):
        return []

    def submit_market_sell(self, http, api_key, *, venue_code, symbol,
                            qty, time_in_force="DAY",
                            client_order_id=None):
        self.market_sells.append({"symbol": symbol, "qty": qty})
        return {"data": {"order_id": "EXIT-1"}, "_http_status": 200}


def _aged_lot():
    return {
        "symbol": "AAA", "qty": 100, "status": "filled",
        "link_id": "L-1", "entry_price": 10.0,
        # >2 trading days before BOTH test dates (Jul 2 and Jul 14).
        "entry_timestamp": "2026-06-26T14:00:00Z",
        "recorded_exposure": 1000.0,
        "child_order_ids": {"target": "", "stop": ""},
    }


def test_pass_skips_holiday_but_fires_on_early_close_day(tmp_path, monkeypatch):
    monkeypatch.setattr(v2, "_CANCEL_VERIFY_ATTEMPTS", 2)
    monkeypatch.setattr(v2, "_CANCEL_VERIFY_SLEEP_S", 0.0)
    cfg = _cfg(tmp_path)

    # Holiday: no exits even at the legacy 15:20 slot.
    state = {"open_positions": {"L-1": _aged_lot()}}
    oa_fake = ExitOA(timings={"is_open": False})
    out = v2.run_time_stop_pass_v2(
        state, cfg, oa_client=oa_fake, api_key="k", http=None,
        now_et=_et("2026-07-02 15:20"),
    )
    assert out == []
    assert oa_fake.market_sells == []

    # Early close 13:00: fires at 12:20. (Same fixture date — drop the
    # per-date cache entry the holiday leg above populated.)
    v2._SESSION_TIMINGS_CACHE.clear()
    v2._TIMINGS_LAST_ATTEMPT.clear()
    state = {"open_positions": {"L-1": _aged_lot()}}
    oa_fake = ExitOA(timings=_open_day("2026-07-02T17:00:00+00:00"))
    out = v2.run_time_stop_pass_v2(
        state, cfg, oa_client=oa_fake, api_key="k", http=None,
        now_et=_et("2026-07-02 12:20"),
    )
    assert out == ["AAA"]
    assert len(oa_fake.market_sells) == 1


def test_pass_uses_injected_timings_over_fetch(tmp_path):
    cfg = _cfg(tmp_path)
    state = {"open_positions": {}}
    oa_fake = ExitOA(timings=_open_day("2026-07-14T20:00:00+00:00"))
    v2.run_time_stop_pass_v2(
        state, cfg, oa_client=oa_fake, api_key="k", http=None,
        now_et=_et("2026-07-14 15:20"),
        timings={"is_open": False},
    )
    assert oa_fake.timings_calls == []   # injected timings win


def test_timings_cached_per_date_with_failure_backoff(tmp_path):
    cfg = _cfg(tmp_path)
    now = _et("2026-07-14 15:20")
    ok = ExitOA(timings=_open_day("2026-07-14T20:00:00+00:00"))
    t1 = v2._session_timings_for_today(
        cfg, oa_client=ok, api_key="k", http=None, now_et=now,
    )
    t2 = v2._session_timings_for_today(
        cfg, oa_client=ok, api_key="k", http=None, now_et=now,
    )
    assert t1 == t2
    assert ok.timings_calls == ["2026-07-14"]   # fetched once

    # Failure path: None cached, no refetch inside the backoff window…
    v2._SESSION_TIMINGS_CACHE.clear()
    v2._TIMINGS_LAST_ATTEMPT.clear()
    failing = ExitOA(timings=None)
    assert v2._session_timings_for_today(
        cfg, oa_client=failing, api_key="k", http=None, now_et=now,
    ) is None
    assert v2._session_timings_for_today(
        cfg, oa_client=failing, api_key="k", http=None, now_et=now,
    ) is None
    assert failing.timings_calls == ["2026-07-14"]
    # …but retried once the backoff has elapsed.
    v2._TIMINGS_LAST_ATTEMPT["2026-07-14"] -= (v2._TIMINGS_RETRY_S + 1)
    v2._session_timings_for_today(
        cfg, oa_client=failing, api_key="k", http=None, now_et=now,
    )
    assert failing.timings_calls == ["2026-07-14", "2026-07-14"]


# ---- client ------------------------------------------------------------------------


def test_fetch_calendar_timings_parses_payload():
    captured: dict = {}

    def handler(req: httpx.Request) -> httpx.Response:
        captured.update(dict(req.url.params))
        assert req.url.path == "/api/v2/calendar/timings"
        return httpx.Response(200, json={"status": "success", "data": {
            "venue_code": "XNAS", "date": "2026-07-14",
            "is_open": True,
            "session_open": "2026-07-14T13:30:00+00:00",
            "session_close": "2026-07-14T20:00:00+00:00",
            "timezone": "America/New_York",
        }})

    with oa.make_http_client(
        "http://oa.test", transport=httpx.MockTransport(handler),
    ) as http:
        t = oa.fetch_calendar_timings(
            http, "k", venue_code="XNAS", date_iso="2026-07-14",
        )
    assert captured == {"venue_code": "XNAS", "date": "2026-07-14"}
    assert t["is_open"] is True
    assert t["session_close"] == "2026-07-14T20:00:00+00:00"


def test_fetch_calendar_timings_failures_return_none():
    def handler_500(req: httpx.Request) -> httpx.Response:
        return httpx.Response(500, json={"error": "boom"})

    def handler_raise(req: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("down", request=req)

    for handler in (handler_500, handler_raise):
        with oa.make_http_client(
            "http://oa.test", transport=httpx.MockTransport(handler),
        ) as http:
            assert oa.fetch_calendar_timings(
                http, "k", venue_code="XNAS", date_iso="2026-07-14",
            ) is None
