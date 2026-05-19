"""Shared fixtures for the bowaka strategy tests.

Keeps individual tests focused on behavior; the harness lives here.

Pattern note: order tests use ``httpx.MockTransport`` (see
``tests/api_v2/test_promoted_orders_alpaca.py``). The MockTransport
factory and fake-fill state container live here so Phase 2/3/4 tests
can share them without reimplementing per-file mocks.
"""
from __future__ import annotations

import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

import httpx
import pytest

# Ensure the strategy module is importable. The script lives outside
# the python package tree by design (it's a /python host artifact), so
# we add its parent directory to sys.path here.
_STRATEGY_DIR = Path(__file__).resolve().parents[2] / "strategies" / "scripts"
if str(_STRATEGY_DIR) not in sys.path:
    sys.path.insert(0, str(_STRATEGY_DIR))


@pytest.fixture
def strategy_module(monkeypatch):
    """Reset module-level state between tests (the shutdown flag is
    a module global).

    Post v1-removal: the v1 bowaka_strategy module lives under
    strategies/scripts/archive/v1_strategy/ and is no longer on
    sys.path. Tests that depend on it skip via importorskip; the
    bulk of v1-pinning tests have been moved to
    tests/strategies/archive/ alongside.
    """
    bw = pytest.importorskip("bowaka_strategy")
    if hasattr(bw, "_shutdown_requested"):
        monkeypatch.setattr(bw, "_shutdown_requested", False)
    return bw


@pytest.fixture
def cfg_dict() -> dict:
    """A canonical config dict that mirrors the YAML template."""
    return {
        "strategy": {
            "name": "Bowaka",
            "strategy_id": "bowaka",
            # Phase 1.2: tests run under env=test so any leaked test
            # event lands in data/test/ rather than contaminating
            # data/paper/. cfg_with_paths overrides the daily_summary
            # path under tmp_path anyway, so the partition resolves
            # under tmp_path/test/ which is fine.
            "environment": "test",
            "is_test_fixture": True,
        },
        "paths": {
            "candidates_path": "data/in_play_candidates.json",
            "state_path": "data/state.json",
            "log_path": "logs/bowaka_strategy.log",
            "kill_switch_dir": ".",
            "daily_summary_path": "data/daily_summary.jsonl",
        },
        "session": {
            "timezone": "America/New_York",
            "start": "09:30",
            "end": "15:55",
            "signal_fade_eval_time": "16:05",
            "loop_interval_seconds": 0.01,
        },
        "prefilter_handshake": {
            "expected_config_hash": None,
            "max_age_trading_days": 1,
        },
        "broker": {
            "base_url_env": "HOST_SERVER",
            "base_url_default": "http://127.0.0.1:5000",
            "timeout_seconds": 15,
            "poll_interval_seconds": 5,
        },
        "sizing": {
            "per_trade_pct": 0.10,
            "max_concurrent_positions": 5,
            "default_venue_code": "XNAS",
        },
        "risk": {
            "daily_loss_pct": 0.03,
            "max_gross_exposure_pct": 0.50,
            "max_per_trade_dollars": None,
            "max_gross_exposure_dollars": None,
        },
        "entry": {
            "bracket_pricing_mode": "actual_fill",
        },
        "exits": {
            "stop_pct": 0.08,
            "target_pct": 0.15,
            "max_hold_days": 3,
            "signal_fade_enabled": True,
            "oco_time_in_force": "GTC",
        },
        "signal_gates": {
            # Optuna best params (2026-05-17). Kept in sync with
            # strategies/scripts/bowaka_prefilter.yaml so any test
            # that writes cfg_dict to disk and calls main() passes
            # the verify_prefilter_handshake step.
            "rvol_min": 1.3844422014336542,
            "atr_pct_min": 0.03051262989343343,
            "range_expansion_min": 1.162515777135367,
            "close_location_min": 0.7340130537157081,
            "ema_distance_min": 0.08883008785458922,
            "ema_slope_min": 0.03594512696636021,
        },
        "indicators": {
            "lookback_days": 20,
            "atr_days": 14,
            "ema_days": 10,
            "ema_slope_lookback": 3,
        },
        "logging": {
            "level": "INFO",
            "file": None,  # disable file logging in tests
        },
    }


@pytest.fixture
def cfg_with_paths(cfg_dict, tmp_path) -> dict:
    """Config with paths anchored under tmp_path so concurrent tests
    don't stomp each other's state files."""
    cfg = dict(cfg_dict)
    cfg["paths"] = {
        **cfg_dict["paths"],
        "candidates_path": str(tmp_path / "in_play_candidates.json"),
        "state_path": str(tmp_path / "state.json"),
        "log_path": str(tmp_path / "bowaka_strategy.log"),
        "kill_switch_dir": str(tmp_path),
        "daily_summary_path": str(tmp_path / "daily_summary.jsonl"),
    }
    return cfg


@pytest.fixture
def fixed_clock():
    """Returns a callable now-provider that the loop accepts."""
    state = {"now": datetime(2026, 5, 5, 18, 0, 0, tzinfo=timezone.utc)}

    def get_now() -> datetime:
        return state["now"]

    get_now.set = lambda dt: state.__setitem__("now", dt)  # type: ignore[attr-defined]
    return get_now


def make_mock_transport(
    handler: Callable[[httpx.Request], httpx.Response],
) -> httpx.MockTransport:
    """Tiny convenience wrapper. Tests can also instantiate directly."""
    return httpx.MockTransport(handler)


@pytest.fixture
def mock_transport_factory():
    return make_mock_transport


@pytest.fixture
def httpx_router():
    """Build a (method, path) → response router for MockTransport tests."""

    routes: dict[tuple[str, str], Callable[[httpx.Request], httpx.Response]] = {}

    def register(method: str, path: str, fn):
        routes[(method.upper(), path)] = fn

    def handler(req: httpx.Request) -> httpx.Response:
        key = (req.method.upper(), req.url.path)
        if key in routes:
            return routes[key](req)
        return httpx.Response(404, json={"error": "no route", "path": req.url.path})

    handler.register = register  # type: ignore[attr-defined]
    handler.routes = routes  # type: ignore[attr-defined]
    return handler
