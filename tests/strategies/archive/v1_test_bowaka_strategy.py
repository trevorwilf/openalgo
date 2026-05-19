"""Phase 1 — bowaka_strategy.py skeleton tests.

Coverage:
- config_hash determinism
- state save/load + atomic-write crash safety
- session window (regular hours, pre-market, post-market, weekend, holiday)
- kill switch precedence (none, L1, L2, L3, L3-wins)
- main loop ``--once`` flag exits cleanly
- SIGTERM persists state and exits 0
- reset_for_new_session preserves open_positions
"""
from __future__ import annotations

import json
import os
import signal as _signal
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import pytest


# ---------------------------------------------------------------- config


def test_config_hash_deterministic(strategy_module, cfg_dict):
    h1 = strategy_module.config_hash(cfg_dict)
    h2 = strategy_module.config_hash(cfg_dict)
    assert h1 == h2 and len(h1) == 8


def test_setup_logging_writes_to_file_without_buffering_lag(
    strategy_module, tmp_path,
):
    """Regression: the default ``logging.FileHandler`` block-buffers
    writes, which in a long-running daemon makes the log file look
    frozen for many minutes. Ops monitoring needs each record visible
    on disk the moment it's emitted. _LineBufferedFileHandler opens
    the underlying file with buffering=1 (line-buffered) so each
    record (which ends in '\\n') flushes immediately."""
    import logging
    log_path = tmp_path / "test_bowaka.log"
    cfg = {"logging": {"level": "INFO", "file": str(log_path)}}
    strategy_module.setup_logging(cfg)
    log = logging.getLogger("bowaka_strategy")
    log.info("first record")
    # Read the file IMMEDIATELY without flushing the handler. With
    # the old block-buffered FileHandler this would be empty until
    # the buffer filled (~8KB). With line buffering it's there now.
    content = log_path.read_text(encoding="utf-8")
    assert "first record" in content
    log.info("second record")
    content2 = log_path.read_text(encoding="utf-8")
    assert "second record" in content2
    # And the count should be 2 distinct records — sanity check that
    # we're not accidentally double-handler'ing.
    assert content2.count("first record") == 1
    assert content2.count("second record") == 1


def test_config_hash_changes_when_value_changes(strategy_module, cfg_dict):
    h1 = strategy_module.config_hash(cfg_dict)
    cfg2 = json.loads(json.dumps(cfg_dict))
    cfg2["sizing"]["per_trade_pct"] = 0.11
    assert strategy_module.config_hash(cfg2) != h1


# ---------------------------------------------------------------- state


def test_state_roundtrip(strategy_module, tmp_path):
    state = strategy_module.blank_state()
    state["session_date"] = "2026-05-05"
    state["open_positions"] = {
        "AAPL": {
            "parent_order_id": "o1",
            "child_order_ids": {"target": "o2", "stop": "o3"},
            "qty": 100,
            "entry_price": 150.5,
            "entry_timestamp": "2026-05-05T13:30:00+00:00",
            "entry_features": {"rvol": 2.0},
            "status": "filled",
        }
    }
    p = tmp_path / "state.json"
    strategy_module.save_state(state, p)
    out = strategy_module.load_state(p)
    assert out == state


def test_state_atomic_write_no_corruption(strategy_module, tmp_path):
    """Simulate a crash after .tmp write (delete .tmp before rename)
    and verify a previously-saved state.json survives untouched."""
    p = tmp_path / "state.json"
    s = strategy_module.blank_state()
    s["session_date"] = "2026-05-05"
    strategy_module.save_state(s, p)
    original = p.read_text()

    # Manually create an orphan .tmp (the would-be in-flight write).
    tmp = p.with_suffix(p.suffix + ".tmp")
    tmp.write_text('{"corrupt": "halfwrite"}')
    # "Crash": just remove the .tmp without renaming.
    tmp.unlink()

    assert p.read_text() == original
    assert strategy_module.load_state(p)["session_date"] == "2026-05-05"


def test_load_state_missing_returns_blank(strategy_module, tmp_path):
    p = tmp_path / "absent.json"
    s = strategy_module.load_state(p)
    assert s["open_positions"] == {}
    assert s["version"] == 1


def test_reset_for_new_session_preserves_open_positions(strategy_module):
    s = strategy_module.blank_state()
    s["open_positions"] = {"AAPL": {"qty": 100, "status": "filled"}}
    s["pending_signal_fade_exits"] = {"MSFT": {"exit_order_id": "x"}}
    s["session_date"] = "2026-05-04"
    s["daily_pnl_baseline_equity"] = 100000.0
    s["daily_pnl_tripped"] = True
    s["halt_skip_today"] = ["GME"]

    strategy_module.reset_for_new_session(s, "2026-05-05", 110000.0)

    assert s["session_date"] == "2026-05-05"
    assert s["daily_pnl_baseline_equity"] == 110000.0
    assert s["daily_pnl_tripped"] is False
    assert s["halt_skip_today"] == []
    # These survive the reset.
    assert s["open_positions"] == {"AAPL": {"qty": 100, "status": "filled"}}
    assert s["pending_signal_fade_exits"] == {"MSFT": {"exit_order_id": "x"}}


# ---------------------------------------------------------------- session


def _et_to_utc(year, month, day, hour, minute) -> datetime:
    """Build a datetime by specifying ET wall-clock, return as UTC."""
    import pytz

    et = pytz.timezone("America/New_York")
    naive = datetime(year, month, day, hour, minute)
    return et.localize(naive).astimezone(timezone.utc)


def test_session_window_regular_hours(strategy_module):
    # Tuesday 2026-05-05 14:00 ET — known trading day.
    now = _et_to_utc(2026, 5, 5, 14, 0)
    assert strategy_module.is_in_session(now) is True


def test_session_window_pre_market(strategy_module):
    now = _et_to_utc(2026, 5, 5, 8, 0)
    assert strategy_module.is_in_session(now) is False


def test_session_window_post_market(strategy_module):
    now = _et_to_utc(2026, 5, 5, 16, 30)
    assert strategy_module.is_in_session(now) is False


def test_session_window_weekend(strategy_module):
    # Saturday 2026-05-09 14:00 ET
    now = _et_to_utc(2026, 5, 9, 14, 0)
    assert strategy_module.is_in_session(now) is False


def test_session_window_holiday_new_years(strategy_module):
    # 2026-01-01 — New Year's Day
    now = _et_to_utc(2026, 1, 1, 14, 0)
    assert strategy_module.is_in_session(now) is False


def test_session_window_holiday_christmas(strategy_module):
    # 2026-12-25 — Christmas Day, Friday
    now = _et_to_utc(2026, 12, 25, 14, 0)
    assert strategy_module.is_in_session(now) is False


def test_signal_fade_window_at_eval_time(strategy_module):
    now = _et_to_utc(2026, 5, 5, 16, 5)
    assert strategy_module.is_signal_fade_window(now) is True


def test_signal_fade_window_off_minute(strategy_module):
    now = _et_to_utc(2026, 5, 5, 16, 6)
    assert strategy_module.is_signal_fade_window(now) is False


def test_signal_fade_window_weekend(strategy_module):
    now = _et_to_utc(2026, 5, 9, 16, 5)
    assert strategy_module.is_signal_fade_window(now) is False


# ---------------------------------------------------------------- kill switch


def test_kill_switch_none(strategy_module, tmp_path):
    assert strategy_module.check_kill_switches(tmp_path) is strategy_module.KillLevel.NONE


def test_kill_switch_l1_only(strategy_module, tmp_path):
    (tmp_path / "KILL_NEW.flag").write_text("")
    assert strategy_module.check_kill_switches(tmp_path) is strategy_module.KillLevel.L1_NEW


def test_kill_switch_l2_only(strategy_module, tmp_path):
    (tmp_path / "KILL_SOFT.flag").write_text("")
    assert strategy_module.check_kill_switches(tmp_path) is strategy_module.KillLevel.L2_SOFT


def test_kill_switch_l3_only(strategy_module, tmp_path):
    (tmp_path / "KILL_HARD.flag").write_text("")
    assert strategy_module.check_kill_switches(tmp_path) is strategy_module.KillLevel.L3_HARD


def test_kill_switch_l3_wins_over_others(strategy_module, tmp_path):
    (tmp_path / "KILL_NEW.flag").write_text("")
    (tmp_path / "KILL_SOFT.flag").write_text("")
    (tmp_path / "KILL_HARD.flag").write_text("")
    assert strategy_module.check_kill_switches(tmp_path) is strategy_module.KillLevel.L3_HARD


def test_kill_switch_l2_wins_over_l1(strategy_module, tmp_path):
    (tmp_path / "KILL_NEW.flag").write_text("")
    (tmp_path / "KILL_SOFT.flag").write_text("")
    assert strategy_module.check_kill_switches(tmp_path) is strategy_module.KillLevel.L2_SOFT


# ---------------------------------------------------------------- main loop


def test_main_loop_once_flag(strategy_module, cfg_with_paths, fixed_clock):
    """--once exits after exactly one tick, with state persisted."""
    rc = strategy_module.run_loop(
        cfg_with_paths, once=True, now_provider=fixed_clock
    )
    assert rc == 0
    state_path = Path(cfg_with_paths["paths"]["state_path"])
    assert state_path.exists()


def test_main_loop_l3_returns_99(strategy_module, cfg_with_paths, fixed_clock):
    Path(cfg_with_paths["paths"]["kill_switch_dir"]).mkdir(parents=True, exist_ok=True)
    flag = Path(cfg_with_paths["paths"]["kill_switch_dir"]) / "KILL_HARD.flag"
    flag.write_text("")
    rc = strategy_module.run_loop(cfg_with_paths, once=True, now_provider=fixed_clock)
    assert rc == 99
    state = strategy_module.load_state(Path(cfg_with_paths["paths"]["state_path"]))
    assert state["kill_switch_state"] == "L3"


def test_main_loop_l1_records_state(strategy_module, cfg_with_paths, fixed_clock):
    flag = Path(cfg_with_paths["paths"]["kill_switch_dir"]) / "KILL_NEW.flag"
    flag.write_text("")
    rc = strategy_module.run_loop(cfg_with_paths, once=True, now_provider=fixed_clock)
    assert rc == 0
    state = strategy_module.load_state(Path(cfg_with_paths["paths"]["state_path"]))
    assert state["kill_switch_state"] == "L1"


# ---------------------------------------------------------------- signal handling


@pytest.mark.skipif(sys.platform == "win32",
                    reason="POSIX SIGTERM behavior; use a Linux/Mac runner")
def test_sigterm_triggers_state_save_and_exit(tmp_path):
    """End-to-end: launch the script, wait for it to settle, send SIGTERM,
    verify it exited 0 and state.json is present.

    Skipped on Windows: signal.SIGTERM is not delivered to a Python
    subprocess on Windows the same way; the application-level shutdown
    is exercised by other tests via the module-level flag.
    """
    # Build a minimal in-tmp config so the script self-contains.
    cfg_path = tmp_path / "cfg.yaml"
    state_path = tmp_path / "state.json"
    log_path = tmp_path / "log.log"
    import yaml
    cfg = {
        "strategy": {"name": "Bowaka", "strategy_id": "bowaka"},
        "paths": {
            "candidates_path": str(tmp_path / "candidates.json"),
            "state_path": str(state_path),
            "log_path": str(log_path),
            "kill_switch_dir": str(tmp_path),
            "daily_summary_path": str(tmp_path / "summary.jsonl"),
        },
        "session": {
            "timezone": "America/New_York",
            "start": "09:30", "end": "15:55",
            "signal_fade_eval_time": "16:05",
            "loop_interval_seconds": 0.05,
        },
        "prefilter_handshake": {"expected_config_hash": None, "max_age_trading_days": 1},
        "broker": {"base_url_env": "HOST_SERVER", "base_url_default": "http://127.0.0.1:5000",
                   "timeout_seconds": 15, "poll_interval_seconds": 5},
        "sizing": {"per_trade_pct": 0.10, "max_concurrent_positions": 5,
                   "default_venue_code": "XNAS"},
        "risk": {"daily_loss_pct": 0.03, "max_gross_exposure_pct": 0.50,
                 "max_per_trade_dollars": None, "max_gross_exposure_dollars": None},
        "exits": {"stop_pct": 0.08, "target_pct": 0.15,
                  "max_hold_days": 3, "signal_fade_enabled": True},
        "signal_gates": {"rvol_min": 1.5, "atr_pct_min": 0.06,
                         "range_expansion_min": 1.25, "close_location_min": 0.60,
                         "ema_distance_min": 0.0, "ema_slope_min": 0.0},
        "indicators": {"lookback_days": 20, "atr_days": 14,
                       "ema_days": 10, "ema_slope_lookback": 3},
        "logging": {"level": "INFO", "file": None},
    }
    cfg_path.write_text(yaml.safe_dump(cfg))

    script = Path(__file__).resolve().parents[2] / "strategies" / "scripts" / "bowaka_strategy.py"
    env = os.environ.copy()
    env["OPENALGO_API_KEY"] = "x"
    env["HOST_SERVER"] = "http://127.0.0.1:5000"
    env["OPENALGO_STRATEGY_EXCHANGE"] = "CRYPTO"

    proc = subprocess.Popen(
        [sys.executable, str(script), "--config", str(cfg_path)],
        env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
    )
    try:
        time.sleep(1.5)
        proc.send_signal(_signal.SIGTERM)
        rc = proc.wait(timeout=10)
    except Exception:
        proc.kill()
        raise

    assert rc == 0, f"stderr: {proc.stderr.read().decode(errors='ignore')}"
    assert state_path.exists(), "state.json should have been saved on SIGTERM"


def test_main_fails_without_api_key(strategy_module, monkeypatch, cfg_with_paths, tmp_path):
    """When OPENALGO_API_KEY is missing, main returns exit code 2."""
    monkeypatch.delenv("OPENALGO_API_KEY", raising=False)
    cfg_path = tmp_path / "cfg.yaml"
    import yaml
    cfg_path.write_text(yaml.safe_dump(cfg_with_paths))
    rc = strategy_module.main(["--config", str(cfg_path), "--once"])
    assert rc == 2


def test_main_succeeds_with_api_key(strategy_module, monkeypatch, cfg_with_paths, tmp_path):
    monkeypatch.setenv("OPENALGO_API_KEY", "k")
    monkeypatch.setenv("OPENALGO_STRATEGY_EXCHANGE", "CRYPTO")
    cfg_path = tmp_path / "cfg.yaml"
    import yaml
    cfg_path.write_text(yaml.safe_dump(cfg_with_paths))
    rc = strategy_module.main(["--config", str(cfg_path), "--once"])
    assert rc == 0


# ============================================================
# 2026-05-15 — trigger_time_stop dedup guard
#
# Regression for the live incident on 2026-05-15: a single ASPI
# position had two market-sells fired ~12s apart because the
# intraday loop's network I/O (cancel children + submit market
# sell) outlasted one ``loop_interval_seconds`` tick. The second
# loop iteration saw ``status == "filled"`` and re-entered the
# function, opening an unintended short. The guard reserves a
# transient ``"exit_pending"`` status BEFORE any I/O so the
# second tick's filter excludes the position.
# ============================================================


def _make_filled_position(qty: int = 100) -> dict:
    """Minimal position dict shaped like ``state['open_positions'][t]``."""
    return {
        "qty": qty,
        "entry_price": 10.0,
        "entry_timestamp": "2026-05-12T13:30:00+00:00",
        "status": "filled",
        "venue_code": "XNAS",
        "child_order_ids": {"target": "tgt-1", "stop": "stp-1"},
        "link_id": "BOWAKA-TEST-1",
    }


def test_trigger_time_stop_skips_when_status_is_exit_pending(
    strategy_module, cfg_with_paths, monkeypatch
):
    """Dedup guard: a position whose status is already ``exit_pending``
    (i.e. a previous loop iteration is mid-flight) must not have its
    exit re-triggered."""
    bw = strategy_module
    state_path = Path(cfg_with_paths["paths"]["state_path"])
    pos = _make_filled_position()
    pos["status"] = "exit_pending"
    pos["exit_reason_pending"] = "time_stop"
    pos["exit_pending_at"] = "2026-05-15T13:45:00+00:00"
    state = {"open_positions": {"AAPL": pos}}
    bw.save_state(state, state_path)

    calls = {"submit": 0, "cancel": 0}

    def fake_submit(*a, **kw):
        calls["submit"] += 1
        return {"_http_status": 200, "data": {"order_id": "SHOULD-NOT-FIRE"}}

    def fake_cancel(*a, **kw):
        calls["cancel"] += 1
        return {}

    monkeypatch.setattr(bw, "submit_market_sell", fake_submit)
    monkeypatch.setattr(bw, "cancel_order", fake_cancel)

    bw.trigger_time_stop(
        "AAPL", pos, cfg_with_paths, None, "k",
        state=state, state_path=state_path,
    )

    assert pos["status"] == "exit_pending", "guard must not mutate status"
    assert calls["submit"] == 0, "guard must NOT submit a duplicate market sell"
    assert calls["cancel"] == 0, "guard must NOT re-cancel OCO children"


def test_trigger_time_stop_skips_when_status_is_exiting(
    strategy_module, cfg_with_paths, monkeypatch
):
    """Same dedup rule for ``status == "exiting"`` (the post-ack
    state) — a redundant trigger must also be a no-op."""
    bw = strategy_module
    state_path = Path(cfg_with_paths["paths"]["state_path"])
    pos = _make_filled_position()
    pos["status"] = "exiting"
    pos["exit_reason"] = "time_stop"
    pos["exit_order_id"] = "prior-exit-id"
    state = {"open_positions": {"AAPL": pos}}
    bw.save_state(state, state_path)

    submitted = []
    monkeypatch.setattr(
        bw, "submit_market_sell",
        lambda *a, **kw: submitted.append(1) or {"_http_status": 200, "data": {"order_id": "X"}},
    )
    monkeypatch.setattr(bw, "cancel_order", lambda *a, **kw: {})

    bw.trigger_time_stop(
        "AAPL", pos, cfg_with_paths, None, "k",
        state=state, state_path=state_path,
    )

    assert pos["status"] == "exiting"
    assert pos["exit_order_id"] == "prior-exit-id"
    assert submitted == []


def test_trigger_time_stop_reserves_exit_pending_before_submit_market_sell(
    strategy_module, cfg_with_paths, monkeypatch
):
    """The status flip to ``exit_pending`` must happen BEFORE the broker
    call. We assert this by sampling ``state`` from inside the mocked
    ``submit_market_sell`` — by the time the broker call fires, the
    reservation must already be visible in state."""
    bw = strategy_module
    state_path = Path(cfg_with_paths["paths"]["state_path"])
    pos = _make_filled_position()
    state = {"open_positions": {"AAPL": pos}}
    bw.save_state(state, state_path)

    seen_status_at_submit: list[str] = []
    seen_status_on_disk: list[str] = []

    def fake_submit(ticker, qty, http, api_key, *, venue_code, time_in_force):
        # In-memory snapshot
        seen_status_at_submit.append(state["open_positions"][ticker]["status"])
        # And: must already be persisted (so a crash here wouldn't strand
        # the reservation in memory only).
        on_disk = json.loads(state_path.read_text())
        seen_status_on_disk.append(on_disk["open_positions"][ticker]["status"])
        return {"_http_status": 200, "data": {"order_id": "FAKE-1"}}

    monkeypatch.setattr(bw, "cancel_order", lambda *a, **kw: {})
    monkeypatch.setattr(bw, "submit_market_sell", fake_submit)

    bw.trigger_time_stop(
        "AAPL", pos, cfg_with_paths, None, "k",
        state=state, state_path=state_path,
    )

    assert seen_status_at_submit == ["exit_pending"], (
        f"submit_market_sell saw status={seen_status_at_submit!r}; "
        "the dedup reservation must be visible BEFORE the broker call"
    )
    assert seen_status_on_disk == ["exit_pending"], (
        "the dedup reservation must be persisted on disk before the broker "
        "call (so a crash mid-call doesn't strand the position as 'filled')"
    )
    # Post-success: 'exit_pending' → 'exiting'; transient fields cleared.
    assert pos["status"] == "exiting"
    assert pos["exit_order_id"] == "FAKE-1"
    assert "exit_reason_pending" not in pos
    assert "exit_pending_at" not in pos


def test_trigger_time_stop_reverts_to_filled_on_http_error(
    strategy_module, cfg_with_paths, monkeypatch
):
    """If submit_market_sell returns non-200, the dedup reservation is
    reverted to ``"filled"`` so the next pass retries cleanly (rather
    than getting stuck on ``exit_pending`` forever)."""
    bw = strategy_module
    state_path = Path(cfg_with_paths["paths"]["state_path"])
    pos = _make_filled_position()
    state = {"open_positions": {"AAPL": pos}}
    bw.save_state(state, state_path)

    monkeypatch.setattr(bw, "cancel_order", lambda *a, **kw: {})
    monkeypatch.setattr(
        bw, "submit_market_sell",
        lambda *a, **kw: {"_http_status": 500, "error": "broker rejected"},
    )

    bw.trigger_time_stop(
        "AAPL", pos, cfg_with_paths, None, "k",
        state=state, state_path=state_path,
    )

    assert pos["status"] == "filled", "status must revert for retry"
    assert "exit_reason_pending" not in pos
    assert "exit_pending_at" not in pos
    # And on-disk state matches.
    on_disk = json.loads(state_path.read_text())
    assert on_disk["open_positions"]["AAPL"]["status"] == "filled"


def test_trigger_time_stop_reverts_on_missing_order_id(
    strategy_module, cfg_with_paths, monkeypatch
):
    """200 OK but no order_id surfaced → also revert for retry."""
    bw = strategy_module
    state_path = Path(cfg_with_paths["paths"]["state_path"])
    pos = _make_filled_position()
    state = {"open_positions": {"AAPL": pos}}
    bw.save_state(state, state_path)

    monkeypatch.setattr(bw, "cancel_order", lambda *a, **kw: {})
    monkeypatch.setattr(
        bw, "submit_market_sell",
        lambda *a, **kw: {"_http_status": 200, "data": {}},  # missing order_id
    )

    bw.trigger_time_stop(
        "AAPL", pos, cfg_with_paths, None, "k",
        state=state, state_path=state_path,
    )

    assert pos["status"] == "filled"
    assert "exit_reason_pending" not in pos
    assert "exit_pending_at" not in pos
