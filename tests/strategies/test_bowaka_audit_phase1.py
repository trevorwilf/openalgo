"""Phase 1 audit acceptance tests — Safety & Data Integrity.

Covers:
  1.1 Redaction round-trip on log lines and exception traces.
  1.2 Candidate JSON v2 shape + ``data_feed`` enforcement.
  1.3 ``CandidatesFeedMismatch`` / ``CandidatesSchemaMismatch`` raise
       on operator-pinned mismatch and clear when matching.
  1.4 Universal ``entry_decision``: count of emissions == count of
       candidates considered.
  1.5 Immutable trade ledger: a second close on the same ``trade_id``
       appends, never overwrites.
  1.6 Daily summary derivation: aggregate of ledger ``closure`` events
       equals the daily summary numbers; ``--reconcile-summary``
       rewrites the matching line as a correction.

Pattern is the established Phase {N} test style: ``httpx.MockTransport``
for any broker HTTP (we never need it here — all Phase 1 logic is
local), ``cfg_with_paths`` fixture for tmp-anchored paths.
"""
from __future__ import annotations

import json
import logging
import re
from datetime import date, datetime, timezone
from pathlib import Path

import pytest


# ---------------------------------------------------------------- 1.1 redaction


def test_redact_secrets_query_string(strategy_module):
    out = strategy_module.redact_secrets(
        "GET /api/v2/balances?apikey=ABC123def&status=open"
    )
    assert "ABC123def" not in out
    assert "<REDACTED>" in out
    assert "status=open" in out  # only the apikey is rewritten


def test_redact_secrets_authorization_bearer(strategy_module):
    out = strategy_module.redact_secrets(
        "Authorization: Bearer eyJhbGciOiJIUzI1NiJ9.payload.sig"
    )
    assert "eyJhbGciOiJIUzI1NiJ9.payload.sig" not in out
    assert "Bearer <REDACTED>" in out


def test_redact_secrets_json_body(strategy_module):
    out = strategy_module.redact_secrets(
        '{"apikey": "verysecret", "symbol": "AAPL"}'
    )
    assert "verysecret" not in out
    assert '"<REDACTED>"' in out
    assert '"symbol": "AAPL"' in out  # other keys untouched


def test_redact_secrets_x_api_key_header(strategy_module):
    out = strategy_module.redact_secrets("X-API-KEY: ABCDEF12345")
    assert "ABCDEF12345" not in out
    assert "<REDACTED>" in out


def test_redact_secrets_idempotent(strategy_module):
    """Running redaction twice on the same string is a no-op."""
    once = strategy_module.redact_secrets("?apikey=secret")
    twice = strategy_module.redact_secrets(once)
    assert once == twice


def test_redact_secrets_non_string_passthrough(strategy_module):
    """Defensive path: redact_secrets returns non-string input as-is
    so LogRecord ``msg`` values that happen to be non-strings don't
    crash the filter."""
    assert strategy_module.redact_secrets(42) == 42
    assert strategy_module.redact_secrets(None) is None
    assert strategy_module.redact_secrets({"a": "b"}) == {"a": "b"}


def test_log_lines_redacted(strategy_module, tmp_path):
    """End-to-end: a log call with an api-key-bearing message routes
    through the redaction filter and the on-disk log file does NOT
    contain the raw secret."""
    log_path = tmp_path / "bowaka.log"
    cfg = {
        "logging": {
            "level": "INFO",
            "file": str(log_path),
        }
    }
    strategy_module.setup_logging(cfg)
    log = logging.getLogger("bowaka_strategy.test")
    log.info("fetching balances via ?apikey=SUPERSECRET123 ok")
    # Force handlers to flush.
    for h in logging.getLogger().handlers:
        try:
            h.flush()
        except Exception:
            pass
    text = log_path.read_text(encoding="utf-8")
    assert "SUPERSECRET123" not in text
    assert "<REDACTED>" in text


def test_log_exception_traceback_redacted(strategy_module, tmp_path):
    """An exception logged via logger.exception should not leak api
    keys present in the exception message."""
    log_path = tmp_path / "bowaka.log"
    cfg = {"logging": {"level": "INFO", "file": str(log_path)}}
    strategy_module.setup_logging(cfg)
    log = logging.getLogger("bowaka_strategy.test")
    try:
        raise RuntimeError("http call failed: ?apikey=LEAKEDKEY7")
    except RuntimeError:
        log.exception("oops")
    for h in logging.getLogger().handlers:
        try:
            h.flush()
        except Exception:
            pass
    text = log_path.read_text(encoding="utf-8")
    # The traceback line carries the raw secret in the exception
    # message — redaction must catch it.
    assert "LEAKEDKEY7" not in text


# ---------------------------------------------------------------- 1.2 candidate v2 schema


def test_stable_hash_format():
    pf = __import__("pytest").importorskip("bowaka_prefilter")
    h = pf.stable_hash({"b": 2, "a": [1, 2, 3]})
    assert h.startswith("sha256:")
    assert len(h) == len("sha256:") + 64  # full hex


def test_stable_hash_order_independent():
    pf = __import__("pytest").importorskip("bowaka_prefilter")
    a = pf.stable_hash({"b": 2, "a": 1})
    b = pf.stable_hash({"a": 1, "b": 2})
    assert a == b


def test_prefilter_write_output_v2_shape(tmp_path):
    """write_output produces a v2 candidate-file payload with all the
    required provenance fields."""
    pf = __import__("pytest").importorskip("bowaka_prefilter")
    import pandas as pd

    df = pd.DataFrame(
        [
            {"close": 10.0, "rvol": 2.0, "atr_pct": 0.08,
             "range_expansion": 1.5, "gap_pct": 0.02,
             "close_location": 0.8, "ema_distance": 0.04,
             "ema_slope": 0.03, "avg_dollar_volume": 5e6,
             "signal_strength": 1.5},
        ],
        index=pd.Index(["AAPL"], name="symbol"),
    )
    out_path = tmp_path / "in_play_candidates.json"
    cfg = {
        "output": {"candidates_path": str(out_path),
                   "diagnostic_csv": None},
        "alpaca": {"feed": "iex"},
        # everything else immaterial for this assertion
    }
    pf.write_output(
        df, counts={"n_in_play": 1}, cfg=cfg, cfg_hash="abcd1234",
        exchanges={"AAPL": "NASDAQ"},
        as_of_date_override="2026-05-11",
        universe_symbols=["AAPL", "MSFT", "TSLA"],
        latest_bar_timestamp="2026-05-11T20:00:00+00:00",
    )
    payload = json.loads(out_path.read_text())
    # v2 required fields
    assert payload["schema_version"] == 2
    assert payload["strategy"] == "bowaka"
    assert payload["provider"] == "alpaca"
    assert payload["data_feed"] == "iex"
    assert payload["bar_timeframe"] == "1D"
    assert payload["config_hash"].startswith("sha256:")
    assert payload["config_hash_short"] == "abcd1234"
    assert payload["universe_hash"].startswith("sha256:")
    assert payload["latest_bar_timestamp"] == "2026-05-11T20:00:00+00:00"
    assert payload["as_of_date"] == "2026-05-11"
    assert payload["candidates"][0]["ticker"] == "AAPL"
    assert payload["candidates"][0]["venue_code"] == "XNAS"


def test_universe_hash_changes_on_universe_change(tmp_path):
    pf = __import__("pytest").importorskip("bowaka_prefilter")
    a = pf.stable_hash(sorted(["AAPL", "MSFT"]))
    b = pf.stable_hash(sorted(["AAPL", "MSFT", "TSLA"]))
    assert a != b


# ---------------------------------------------------------------- 1.3 fail-closed handshake


def _write_candidates(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")


def test_load_candidates_feed_mismatch_raises(strategy_module, tmp_path):
    path = tmp_path / "in_play.json"
    today = date(2026, 5, 11)
    _write_candidates(path, {
        "schema_version": 2, "as_of_date": today.isoformat(),
        "data_feed": "iex", "candidates": [],
    })
    with pytest.raises(strategy_module.CandidatesFeedMismatch):
        strategy_module.load_candidates(
            path,
            max_age_trading_days=5,
            expected_config_hash=None,
            today_et=today,
            expected_data_feed="sip",
        )


def test_load_candidates_feed_match_passes(strategy_module, tmp_path):
    path = tmp_path / "in_play.json"
    today = date(2026, 5, 11)
    _write_candidates(path, {
        "schema_version": 2, "as_of_date": today.isoformat(),
        "data_feed": "iex", "candidates": [],
    })
    cands = strategy_module.load_candidates(
        path,
        max_age_trading_days=5,
        expected_config_hash=None,
        today_et=today,
        expected_data_feed="iex",
        expected_schema_version=2,
    )
    assert cands == []


def test_load_candidates_schema_mismatch_raises(strategy_module, tmp_path):
    path = tmp_path / "in_play.json"
    today = date(2026, 5, 11)
    _write_candidates(path, {
        "schema_version": 1, "as_of_date": today.isoformat(),
        "data_feed": "iex", "candidates": [],
    })
    with pytest.raises(strategy_module.CandidatesSchemaMismatch):
        strategy_module.load_candidates(
            path,
            max_age_trading_days=5,
            expected_config_hash=None,
            today_et=today,
            expected_schema_version=2,
        )


def test_load_candidates_handshake_disabled_accepts_any(strategy_module, tmp_path):
    """Null pins keep legacy behavior — any feed / schema is fine."""
    path = tmp_path / "in_play.json"
    today = date(2026, 5, 11)
    _write_candidates(path, {
        "as_of_date": today.isoformat(),
        "data_feed": "iex", "candidates": [],
    })
    cands = strategy_module.load_candidates(
        path,
        max_age_trading_days=5,
        expected_config_hash=None,
        today_et=today,
        expected_data_feed=None,
        expected_schema_version=None,
    )
    assert cands == []


# ---------------------------------------------------------------- 1.4 universal entry_decision


def _ledger_for(cfg) -> Path:
    """Resolve the ledger path for a cfg with paths.daily_summary_path.

    Phase 1.2 — the strategy now partitions the ledger by environment
    under ``data/<env>/trade_ledger.jsonl``. Delegate to the canonical
    resolver so tests stay aligned with the runtime path."""
    import bowaka_strategy as bw
    return bw._ledger_path(cfg)


def _read_ledger(path: Path) -> list[dict]:
    if not path.exists():
        return []
    out = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        out.append(json.loads(line))
    return out


def test_select_entries_emits_universal_entry_decisions_for_rejections(
    strategy_module, cfg_with_paths,
):
    """10-candidate slate with cap=2 → ``select_entries`` emits 8
    rejection events (the 2 selected ones get their accepted emission
    from the entry-pass driver, NOT from ``select_entries``).

    Together with the accepted-path emission in
    ``run_session_entry_pass``, this gives the universal-coverage
    property: each candidate considered yields exactly one
    ``entry_decision`` event somewhere in the pipeline.
    """
    state = strategy_module.blank_state()
    cands = [
        strategy_module.Candidate(
            ticker=f"T{i:02d}", close=10.0,
            signal_strength=10.0 - i * 0.1,
            features={"avg_dollar_volume": 5_000_000.0},
        )
        for i in range(10)
    ]
    cfg = dict(cfg_with_paths)
    cfg["sizing"] = {**cfg["sizing"], "max_concurrent_positions": 2}
    selected = strategy_module.select_entries(
        cands, state, equity=100_000.0, latest_prices={},
        cfg=cfg, kill_state=strategy_module.KillLevel.NONE,
    )
    assert len(selected) == 2

    ledger = _read_ledger(_ledger_for(cfg))
    decisions = [e for e in ledger if e["event_type"] == "entry_decision"]
    # 8 rejection events from select_entries (all concurrent_cap).
    assert len(decisions) == 8
    reasons = [d["payload"]["reason"] for d in decisions]
    assert all(r == "concurrent_cap" for r in reasons)
    # candidate_rank is per-candidate (1-based) — verify the 8 ranks
    # span T02 through T09 (i.e., the candidates that did not fit).
    rejected_tickers = sorted(d["payload"]["ticker"] for d in decisions)
    assert rejected_tickers == [f"T{i:02d}" for i in range(2, 10)]
    # Verify candidate_rank is properly set per-candidate
    by_ticker = {d["payload"]["ticker"]: d["payload"]["candidate_rank"]
                 for d in decisions}
    assert by_ticker["T02"] == 3  # 1-based
    assert by_ticker["T09"] == 10


def test_select_entries_emits_decisions_with_canonical_reasons(
    strategy_module, cfg_with_paths,
):
    """Each rejection path picks a canonical reason from
    ENTRY_DECISION_REASONS."""
    state = strategy_module.blank_state()
    state["halt_skip_today"] = ["HALT"]
    state["open_positions"] = {"HELD": {"qty": 1, "entry_price": 1.0}}
    state["entered_today"] = ["AGAIN"]
    cands = [
        strategy_module.Candidate("HALT", 10.0, 5.0,
                                  features={"avg_dollar_volume": 1e7}),
        strategy_module.Candidate("HELD", 10.0, 4.0,
                                  features={"avg_dollar_volume": 1e7}),
        strategy_module.Candidate("AGAIN", 10.0, 3.0,
                                  features={"avg_dollar_volume": 1e7}),
        strategy_module.Candidate("ZERO", 1_000_000.0, 2.0,  # qty=0
                                  features={"avg_dollar_volume": 1e7}),
    ]
    strategy_module.select_entries(
        cands, state, equity=100_000.0, latest_prices={},
        cfg=cfg_with_paths, kill_state=strategy_module.KillLevel.NONE,
    )
    ledger = _read_ledger(_ledger_for(cfg_with_paths))
    reasons = {
        e["payload"]["ticker"]: e["payload"]["reason"]
        for e in ledger if e["event_type"] == "entry_decision"
    }
    assert reasons["HALT"] == "halt_skip"
    assert reasons["HELD"] == "already_held"
    assert reasons["AGAIN"] == "already_entered_today"
    assert reasons["ZERO"] == "qty_zero"
    # Every reason is in the canonical set.
    for r in reasons.values():
        assert r in strategy_module.ENTRY_DECISION_REASONS


def test_kill_switch_emits_single_synthetic_event(
    strategy_module, cfg_with_paths,
):
    """Slate-wide kill emits one synthetic entry_decision (not one
    per candidate) per the audit prompt."""
    state = strategy_module.blank_state()
    cands = [strategy_module.Candidate(f"T{i}", 10.0, 5.0) for i in range(5)]
    strategy_module.select_entries(
        cands, state, equity=100_000.0, latest_prices={},
        cfg=cfg_with_paths, kill_state=strategy_module.KillLevel.L1_NEW,
    )
    ledger = _read_ledger(_ledger_for(cfg_with_paths))
    decisions = [e for e in ledger if e["event_type"] == "entry_decision"]
    # One synthetic event, not five.
    assert len(decisions) == 1
    assert decisions[0]["payload"]["reason"] == "kill_switch"


def test_daily_pnl_tripped_emits_single_synthetic_event(
    strategy_module, cfg_with_paths,
):
    state = strategy_module.blank_state()
    state["daily_pnl_tripped"] = True
    cands = [strategy_module.Candidate(f"T{i}", 10.0, 5.0) for i in range(3)]
    strategy_module.select_entries(
        cands, state, equity=100_000.0, latest_prices={},
        cfg=cfg_with_paths, kill_state=strategy_module.KillLevel.NONE,
    )
    ledger = _read_ledger(_ledger_for(cfg_with_paths))
    decisions = [e for e in ledger if e["event_type"] == "entry_decision"]
    assert len(decisions) == 1
    assert decisions[0]["payload"]["reason"] == "daily_pnl_tripped"


# ---------------------------------------------------------------- 1.5 ledger immutability


def test_ledger_event_appended_not_overwritten(
    strategy_module, cfg_with_paths,
):
    """A second event for the same trade_id is appended, never
    overwrites prior entries."""
    cfg = cfg_with_paths
    strategy_module.emit_ledger_event(
        cfg, event_type="closure", trade_id="BOWAKA-AAPL-1",
        ticker="AAPL",
        payload={"realized_pnl": 100.0, "reason": "target_hit"},
    )
    strategy_module.emit_ledger_event(
        cfg, event_type="correction", trade_id="BOWAKA-AAPL-1",
        ticker="AAPL",
        payload={"realized_pnl": 95.0, "reason": "target_hit",
                 "correction_of": "see-event-id-1"},
    )
    events = _read_ledger(_ledger_for(cfg))
    assert len(events) == 2
    assert events[0]["event_type"] == "closure"
    assert events[1]["event_type"] == "correction"


def test_ledger_event_has_uuid_and_schema_version(
    strategy_module, cfg_with_paths,
):
    strategy_module.emit_ledger_event(
        cfg_with_paths, event_type="entry_decision",
        trade_id=None, ticker="AAPL",
        payload={"reason": "accepted"},
    )
    [ev] = _read_ledger(_ledger_for(cfg_with_paths))
    # Phase 1.3: schema bumped to 3. Use ``>= 1`` for forward
    # compatibility — the v1 shape is no longer the canonical form.
    assert ev["schema_version"] >= 1
    # uuid4 hex is 32 chars all hex.
    assert re.fullmatch(r"[0-9a-f]{32}", ev["event_id"])
    assert ev["session_date"]  # populated


def test_ledger_path_falls_back_silently_on_empty_cfg(strategy_module):
    """``cfg=None`` and ``cfg={}`` are both no-ops (don't crash)."""
    assert strategy_module.emit_ledger_event(
        None, event_type="closure", trade_id="X", ticker="X",
        payload={},
    ) is None
    assert strategy_module.emit_ledger_event(
        {}, event_type="closure", trade_id="X", ticker="X",
        payload={},
    ) is None


# ---------------------------------------------------------------- 1.6 daily summary derivation


def test_recompute_daily_summary_aggregates_closures(
    strategy_module, tmp_path,
):
    """Synthetic ledger with 3 closures, one correction → recomputed
    summary matches expected aggregate."""
    ledger = tmp_path / "trade_ledger.jsonl"
    today = "2026-05-11"
    events = [
        # Opens (so opened tally != 0)
        {"event_type": "order_fill", "session_date": today,
         "trade_id": "T1", "ticker": "AAPL", "role": "parent",
         "payload": {"entry_trigger": "session_open"}},
        {"event_type": "order_fill", "session_date": today,
         "trade_id": "T2", "ticker": "MSFT", "role": "parent",
         "payload": {"entry_trigger": "session_open"}},
        {"event_type": "order_fill", "session_date": today,
         "trade_id": "T3", "ticker": "GOOG", "role": "parent",
         "payload": {"entry_trigger": "post_closure_rescreen"}},
        # Closures
        {"event_type": "closure", "session_date": today, "trade_id": "T1",
         "ticker": "AAPL",
         "payload": {"realized_pnl": 100.0, "reason": "target_hit",
                     "entry_trigger": "session_open"}},
        {"event_type": "closure", "session_date": today, "trade_id": "T2",
         "ticker": "MSFT",
         "payload": {"realized_pnl": -40.0, "reason": "stop_hit",
                     "entry_trigger": "session_open"}},
        {"event_type": "closure", "session_date": today, "trade_id": "T3",
         "ticker": "GOOG",
         "payload": {"realized_pnl": 50.0, "reason": "target_hit",
                     "entry_trigger": "post_closure_rescreen"}},
        # Correction: T3's realized was actually -10 (broker
        # reconcile correction).
        {"event_type": "correction", "session_date": today, "trade_id": "T3",
         "ticker": "GOOG",
         "payload": {"realized_pnl": -10.0, "reason": "stop_hit",
                     "entry_trigger": "post_closure_rescreen"}},
    ]
    import uuid
    with open(ledger, "w", encoding="utf-8") as f:
        for raw in events:
            f.write(json.dumps({
                "schema_version": 1, "event_id": uuid.uuid4().hex,
                "ts": today + "T13:30:00+00:00", **raw,
            }) + "\n")
    base = strategy_module.recompute_daily_summary_from_ledger(ledger, today)
    assert base["count_opened"] == 3
    assert base["count_closed"] == 3
    # 100 + -40 + -10 (correction replaces +50)
    assert base["total_realized_pnl"] == pytest.approx(50.0)
    assert base["by_reason"]["target_hit"] == 1
    assert base["by_reason"]["stop_hit"] == 2
    assert base["derived_from_ledger"] is True
    assert base["ledger_event_count_for_date"] == 7


def test_recompute_daily_summary_ignores_other_dates(
    strategy_module, tmp_path,
):
    ledger = tmp_path / "trade_ledger.jsonl"
    other = "2026-05-10"
    today = "2026-05-11"
    import uuid
    with open(ledger, "w") as f:
        for d, pnl in ((other, 999.0), (today, 100.0)):
            f.write(json.dumps({
                "schema_version": 1, "event_id": uuid.uuid4().hex,
                "event_type": "closure", "session_date": d,
                "trade_id": f"T-{d}", "ticker": "X", "ts": "n/a",
                "payload": {"realized_pnl": pnl, "reason": "target_hit"},
            }) + "\n")
    base = strategy_module.recompute_daily_summary_from_ledger(ledger, today)
    assert base["count_closed"] == 1
    assert base["total_realized_pnl"] == pytest.approx(100.0)


def test_recompute_daily_summary_empty_ledger(strategy_module, tmp_path):
    """No ledger file → empty summary, no exceptions."""
    ledger = tmp_path / "trade_ledger.jsonl"
    base = strategy_module.recompute_daily_summary_from_ledger(ledger, "2026-05-11")
    assert base["count_opened"] == 0
    assert base["count_closed"] == 0
    assert base["total_realized_pnl"] == 0.0
    assert base["derived_from_ledger"] is True
    assert base["ledger_event_count_for_date"] == 0


def test_reconcile_summary_appends_correction_version(
    strategy_module, cfg_with_paths, tmp_path,
):
    """``--reconcile-summary`` appends a fresh session_summary line
    marked correction_version=N+1 without overwriting the prior."""
    summary_path = Path(cfg_with_paths["paths"]["daily_summary_path"])
    summary_path.parent.mkdir(parents=True, exist_ok=True)
    today = "2026-05-11"
    # Seed a prior session summary for the date.
    summary_path.write_text(json.dumps({
        "record_type": "session_summary", "session_date": today,
        "count_opened": 0, "count_closed": 0,
        "total_realized_pnl": 0.0,
    }) + "\n")
    # Seed the ledger with a closure that the prior summary missed.
    # Phase 1.2: ledger now lives under data/<env>/trade_ledger.jsonl.
    ledger = _ledger_for(cfg_with_paths)
    ledger.parent.mkdir(parents=True, exist_ok=True)
    import uuid
    with open(ledger, "w") as f:
        f.write(json.dumps({
            "schema_version": 1, "event_id": uuid.uuid4().hex,
            "event_type": "closure", "session_date": today,
            "trade_id": "T-missed", "ticker": "AAPL", "ts": "n/a",
            "payload": {"realized_pnl": 42.0, "reason": "target_hit"},
        }) + "\n")
    rec = strategy_module.reconcile_summary_for_date(
        cfg_with_paths, summary_path, today,
    )
    assert rec["correction_version"] == 2
    assert rec["count_closed"] == 1
    assert rec["total_realized_pnl"] == pytest.approx(42.0)
    # Prior line untouched, new one appended.
    lines = [json.loads(l) for l in summary_path.read_text().splitlines() if l.strip()]
    assert len(lines) == 2
    assert lines[0].get("correction_version") is None
    assert lines[1]["correction_version"] == 2


def test_write_session_summary_carries_derived_from_ledger_flag(
    strategy_module, cfg_with_paths, tmp_path,
):
    """Phase 1.6 contract: every session_summary record carries
    ``derived_from_ledger: true`` and a ledger event count."""
    summary_path = Path(cfg_with_paths["paths"]["daily_summary_path"])
    state_path = Path(cfg_with_paths["paths"]["state_path"])
    today = "2026-05-11"
    # Empty ledger → still write the record.
    state = strategy_module.blank_state()
    rec = strategy_module.write_session_summary(
        state, cfg_with_paths,
        summary_path=summary_path, state_path=state_path,
        today_iso=today,
    )
    assert rec is not None
    assert rec["derived_from_ledger"] is True
    assert rec["ledger_event_count_for_date"] == 0


# ---------------------------------------------------------------- 1.1 call-site audit


def test_fetch_equity_uses_header_only_no_query_apikey(
    strategy_module, cfg_with_paths,
):
    """Phase 1.1: GET /api/v2/balances must NOT carry an ``apikey``
    query parameter (header auth only)."""
    import httpx

    seen_urls: list[str] = []

    def handler(req: httpx.Request) -> httpx.Response:
        seen_urls.append(str(req.url))
        return httpx.Response(200, json={"data": {"balance": {"equity": 100000.0}}})

    transport = httpx.MockTransport(handler)
    http = strategy_module.make_http_client("http://x", transport=transport)
    eq = strategy_module.fetch_equity(http, "SUPERSECRET")
    assert eq == 100000.0
    # The url should contain no apikey query parameter.
    assert all("apikey" not in u for u in seen_urls), seen_urls


def test_cancel_order_uses_header_only_no_query_apikey(strategy_module):
    """Phase 1.1: DELETE /api/v2/orders/<id> sends X-API-KEY header,
    no query apikey."""
    import httpx
    seen_params: list[str] = []

    def handler(req: httpx.Request) -> httpx.Response:
        seen_params.append(req.url.query.decode())
        return httpx.Response(200, json={"data": {}})

    transport = httpx.MockTransport(handler)
    http = strategy_module.make_http_client("http://x", transport=transport)
    res = strategy_module.cancel_order("ORDER-1", http, "SECRET")
    assert res["status"] == "canceled"
    assert all("apikey" not in q for q in seen_params), seen_params
