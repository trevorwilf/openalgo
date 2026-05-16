#!/usr/bin/env python3
"""
bowaka_strategy.py — OpenAlgo /python strategy that consumes the Bowaka
prefilter and trades through Alpaca via OpenAlgo's promoted v2 API.

Companion artifact: ``strategies/scripts/bowaka_prefilter.py`` (already
built, scheduled, running). This file is the trading-side counterpart.

Phase 1 — skeleton: CLI bootstrap, config loader, logging, state
management, session window check, kill switch detection, signal
handlers, no-op main loop. Order placement, candidate ingestion, and
exits arrive in later phases.

State is modelled as a plain ``TypedDict``; the schema is documented
inline below so the runbook can point at one canonical place.

Auth: ``OPENALGO_API_KEY`` from env. Host: ``HOST_SERVER`` (default
http://127.0.0.1:5000). The ``/python`` host launches with
``OPENALGO_STRATEGY_EXCHANGE=CRYPTO`` so the host's Indian holiday gate
does not fire — the strategy enforces its own NYSE session window.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import logging
import math
import os
import re
import signal
import socket
import subprocess
import sys
import time
import uuid
from dataclasses import dataclass, field
from datetime import date, datetime, time as _dtime, timedelta, timezone
from enum import Enum
from pathlib import Path
from typing import Any, TypedDict

import httpx
import numpy as np
import pandas as pd
import pandas_market_calendars as mcal
import yaml

LOG = logging.getLogger("bowaka_strategy")


# ---------------------------------------------------------------- Phase 1.1 — secret redaction
#
# Every log line passes through ``redact_secrets`` via the
# ``_RedactingFilter`` attached in ``setup_logging``. Patterns cover
# the three places API keys / bearer tokens can leak into log text:
#
#   1. Query strings:        ``apikey=ABC`` / ``api_key=ABC``
#   2. Authorization header: ``Authorization: Bearer ABC``
#   3. JSON-as-text bodies:  ``"apikey": "ABC"`` / ``"api_key": "ABC"``
#   4. X-API-KEY header:     ``X-API-KEY: ABC`` / ``X-APIKEY: ABC``
#
# Each match is rewritten with the literal placeholder ``<REDACTED>``
# so the surrounding structure is preserved (useful for postmortem)
# but the secret material is unrecoverable.
SECRET_PATTERNS: list[tuple[re.Pattern[str], str]] = [
    # Query-string-style: ?apikey=ABC or &api_key=ABC. The token
    # character class matches typical API-key alphabets (alnum + . _ -)
    # but not the separator (& or whitespace) so we stop at the
    # parameter boundary.
    (re.compile(r"(?i)(\bapi[_-]?key)=([A-Za-z0-9._\-]+)"),
     r"\1=<REDACTED>"),
    # Authorization: Bearer <token>
    (re.compile(r"(?i)(Authorization:\s*Bearer)\s+([A-Za-z0-9._\-]+)"),
     r"\1 <REDACTED>"),
    # JSON-as-text: "apikey": "ABC"  /  'api_key': 'ABC'
    (re.compile(r"""(?i)(["']api[_-]?key["']\s*:\s*)["']([^"']+)["']"""),
     r'\1"<REDACTED>"'),
    # X-API-KEY (and X-APIKEY) header lines
    (re.compile(r"(?i)(X-API-?KEY:\s*)([A-Za-z0-9._\-]+)"),
     r"\1<REDACTED>"),
]


def redact_secrets(text: str) -> str:
    """Apply every ``SECRET_PATTERNS`` substitution to ``text``.

    Idempotent — running it twice on the same string is a no-op.
    Returns the input unchanged when it is not a string (defensive
    for non-string LogRecord ``msg`` values).
    """
    if not isinstance(text, str):
        return text
    out = text
    for pat, repl in SECRET_PATTERNS:
        out = pat.sub(repl, out)
    return out


class _RedactingFilter(logging.Filter):
    """Logging filter that runs every record through ``redact_secrets``.

    Applied to BOTH the message template and any positional / keyword
    args, because the LogRecord's final-formatted message is built
    from ``msg % args`` at handler-emit time. Filtering at ``filter()``
    runs before that interpolation, so we have to redact the args
    individually — otherwise a call like
    ``LOG.info("url=%s", "https://x?apikey=ABC")`` would emit the
    secret intact.

    Exception tracebacks (``record.exc_info``) need special handling:
    the formatter formats them at handler-emit time, after the filter
    chain. We pre-format the traceback here, redact it, and cache the
    result on ``record.exc_text`` so the formatter uses our version
    instead of re-formatting from ``exc_info``.
    """

    def filter(self, record: logging.LogRecord) -> bool:  # type: ignore[override]
        try:
            if isinstance(record.msg, str):
                record.msg = redact_secrets(record.msg)
            if record.args:
                if isinstance(record.args, tuple):
                    record.args = tuple(
                        redact_secrets(a) if isinstance(a, str) else a
                        for a in record.args
                    )
                elif isinstance(record.args, dict):
                    record.args = {
                        k: (redact_secrets(v) if isinstance(v, str) else v)
                        for k, v in record.args.items()
                    }
            # Pre-format and redact the traceback so the handler's
            # formatter uses our redacted exc_text rather than
            # re-formatting raw exc_info at emit time.
            if record.exc_info and not record.exc_text:
                import traceback
                tb_text = "".join(
                    traceback.format_exception(*record.exc_info)
                )
                record.exc_text = redact_secrets(tb_text).rstrip()
            elif record.exc_text:
                record.exc_text = redact_secrets(record.exc_text)
            if getattr(record, "stack_info", None):
                record.stack_info = redact_secrets(record.stack_info)
        except Exception:
            # Filter must not raise — better to log unredacted than
            # to drop a critical log line.
            pass
        return True

# ---------------------------------------------------------------- state schema

# State JSON shape (version 1):
#
#   {
#     "version": 1,
#     "strategy_id": "bowaka",
#     "session_date": null | "YYYY-MM-DD",
#     "daily_pnl_baseline_equity": null | float,
#     "daily_pnl_tripped": false,
#     "open_positions": {
#       "<ticker>": {
#         "parent_order_id": str,
#         "child_order_ids": {"target": str, "stop": str},
#         "qty": int,
#         "entry_price": float | null,
#         "entry_timestamp": iso8601,
#         "entry_features": {...},
#         "status": "pending_fill" | "filled" | "exiting"
#       }
#     },
#     "pending_signal_fade_exits": {
#       "<ticker>": {"submitted_at": iso8601, "exit_order_id": str}
#     },
#     "halt_skip_today": ["<ticker>", ...],
#     "kill_switch_state": null | "L1" | "L2" | "L3"
#   }


class State(TypedDict, total=False):
    version: int
    strategy_id: str
    session_date: str | None
    daily_pnl_baseline_equity: float | None
    daily_pnl_tripped: bool
    open_positions: dict[str, dict[str, Any]]
    pending_signal_fade_exits: dict[str, dict[str, Any]]
    halt_skip_today: list[str]
    kill_switch_state: str | None
    # Post-closure rescreen support (added with the policy):
    # entered_today: every ticker submitted today regardless of trigger.
    #   The same-day re-entry block reads this so a name that stopped
    #   out in the morning is not re-entered in the afternoon.
    # daily_entries_count: total submitted entries today; bounded by
    #   risk.max_total_entries_per_day to prevent runaway chaining.
    # rescreen_pending: flag set by every intraday closure path; read
    #   once per tick at end-of-tick so multiple simultaneous closures
    #   debounce to one rescreen invocation.
    # rescreens_today / post_closure_entries_today: pure telemetry
    #   carried into the daily session_summary record.
    entered_today: list[str]
    daily_entries_count: int
    rescreen_pending: bool
    rescreens_today: int
    post_closure_entries_today: int
    # Phase 3.3 — daily-risk circuit breakers.
    daily_stopouts_count: int
    consecutive_stopouts_count: int
    block_new_entries_today: bool
    new_entries_blocked_reason: str | None
    daily_realized_pnl_strategy: float
    daily_realized_pnl_bankroll_pct: float
    # Bankroll envelope (cfg.bankroll). When the operator enables the
    # bankroll feature, all sizing reads `bankroll.current_dollars` as
    # the equity-equivalent, not broker equity. Seeded on first init
    # or when cfg.bankroll.reset_token changes. Grows / shrinks with
    # bowaka's own realized P&L, capped above at cap_dollars and
    # clamped below at $0.
    bankroll: dict[str, Any]


def blank_state() -> State:
    return {
        "version": 1,
        "strategy_id": "bowaka",
        "session_date": None,
        "daily_pnl_baseline_equity": None,
        "daily_pnl_tripped": False,
        "open_positions": {},
        "pending_signal_fade_exits": {},
        "halt_skip_today": [],
        "kill_switch_state": None,
        "entered_today": [],
        "daily_entries_count": 0,
        "rescreen_pending": False,
        "rescreens_today": 0,
        "post_closure_entries_today": 0,
        # Phase 3.3 — circuit-breaker daily state.
        "daily_stopouts_count": 0,
        "consecutive_stopouts_count": 0,
        "block_new_entries_today": False,
        "new_entries_blocked_reason": None,
        "daily_realized_pnl_strategy": 0.0,
        "daily_realized_pnl_bankroll_pct": 0.0,
    }


# ---------------------------------------------------------------- Phase 2 protection state machine
#
# The protection_state derivation drives every "is this position
# safe to leave running" decision. The state names below are the
# canonical machine-readable values. The legacy
# ``pos["protection_status"]`` string is now derived from the
# broker truth (open orders), not trusted on its face — the 2026-
# 05-15 incident showed that a stale string can leave four
# positions wearing ``oco_attached`` with empty child IDs (no real
# protection live at the broker).

PROTECTION_STATES = (
    "flat",
    "pending_entry",
    "filled_unprotected",
    "oco_attached_confirmed",
    "fallback_stop_attached_confirmed",
    "exit_order_pending",
    "exit_order_accepted",
    "rebracket_pending",
    "protection_repair_failed",
    "closed",
)

_ACTIVE_OR_ACCEPTED_BROKER_STATUSES = {
    "new", "accepted", "pending_new", "partially_filled",
    "NEW", "ACCEPTED", "PENDING_NEW", "PARTIALLY_FILLED",
}


# ---------------------------------------------------------------- kill switch


class KillLevel(Enum):
    NONE = "NONE"
    L1_NEW = "L1_NEW"
    L2_SOFT = "L2_SOFT"
    L3_HARD = "L3_HARD"


KILL_FLAG_NEW = "KILL_NEW.flag"
KILL_FLAG_SOFT = "KILL_SOFT.flag"
KILL_FLAG_HARD = "KILL_HARD.flag"


def check_kill_switches(switch_dir: Path) -> KillLevel:
    """Highest-precedence flag wins: L3 > L2 > L1."""
    if (switch_dir / KILL_FLAG_HARD).exists():
        return KillLevel.L3_HARD
    if (switch_dir / KILL_FLAG_SOFT).exists():
        return KillLevel.L2_SOFT
    if (switch_dir / KILL_FLAG_NEW).exists():
        return KillLevel.L1_NEW
    return KillLevel.NONE


# ---------------------------------------------------------------- config


def load_config(path: str) -> dict:
    with open(path) as f:
        return yaml.safe_load(f)


def config_hash(cfg: dict) -> str:
    """Stable short hash so the strategy can detect a config drift —
    matches the prefilter's hashing scheme byte-for-byte (sha256, first
    8 hex chars, sort_keys, default=str)."""
    blob = json.dumps(cfg, sort_keys=True, default=str).encode()
    return hashlib.sha256(blob).hexdigest()[:8]


# ---- Phase 1.3 — schema v3 envelope helpers ----
#
# Every ledger event carries the run_id / daemon_instance_id /
# strategy_version / config_hash_full / analysis_epoch so analyses can
# join across runs and detect config drift after the fact. The values
# are computed once per process and cached.

DEFAULT_ANALYSIS_EPOCH: str = "bowaka_paper_epoch_2026_05_16_v1"


def _strategy_version() -> str:
    """Return short git sha if running from a repo, else 'unknown'."""
    try:
        sha = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],
            capture_output=True,
            text=True,
            timeout=2,
            check=False,
            cwd=str(Path(__file__).resolve().parent),
        ).stdout.strip()
        return sha or "unknown"
    except Exception:
        return "unknown"


_RUN_ID_CACHE: str | None = None


def _run_id(environment: str | None = None) -> str:
    """Stable per-process run identifier of the form
    ``<iso-z>_bowaka_<env>_<6-hex>`` (iso colons replaced with ``-``
    so the value is safe as part of a filename on Windows). Cached
    for the life of the process so all events from a run share the
    same id."""
    global _RUN_ID_CACHE
    if _RUN_ID_CACHE is None:
        env = (environment or os.environ.get("BOWAKA_ENV") or "paper").lower()
        # Colons are illegal in Windows filenames — replace them so
        # the run_id can be embedded in the config-snapshot path.
        ts = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H-%M-%SZ")
        _RUN_ID_CACHE = f"{ts}_bowaka_{env}_{uuid.uuid4().hex[:6]}"
    return _RUN_ID_CACHE


_DAEMON_ID_CACHE: str | None = None


def _daemon_instance_id() -> str:
    """Stable per-process daemon identifier of the form
    ``<host>_<pid>_<8-hex>``."""
    global _DAEMON_ID_CACHE
    if _DAEMON_ID_CACHE is None:
        _DAEMON_ID_CACHE = (
            f"{socket.gethostname()}_{os.getpid()}_{uuid.uuid4().hex[:8]}"
        )
    return _DAEMON_ID_CACHE


def _reset_run_id_cache_for_tests() -> None:
    """Test-only escape hatch. Lets a test simulate a new process
    without spawning a real subprocess. Do not call from production
    code."""
    global _RUN_ID_CACHE, _DAEMON_ID_CACHE
    _RUN_ID_CACHE = None
    _DAEMON_ID_CACHE = None


def _config_hash_full(cfg: dict) -> str:
    """Full sha256 hex of the cfg dump. ``config_hash`` returns the
    first 8 chars for log lines; this returns the canonical 64-char
    full digest so analyses can detect even tiny config drift."""
    blob = json.dumps(cfg, sort_keys=True, default=str).encode("utf-8")
    return hashlib.sha256(blob).hexdigest()


def _strategy_environment(cfg: dict | None) -> str:
    """Resolve the environment string. Defaults to ``"paper"`` if
    unset. Valid values: ``paper`` | ``test`` | ``live``."""
    if cfg is None:
        return "paper"
    env = ((cfg.get("strategy") or {}).get("environment") or "paper").lower()
    return env


def _analysis_epoch(cfg: dict | None) -> str:
    if cfg is None:
        return DEFAULT_ANALYSIS_EPOCH
    return (
        (cfg.get("strategy") or {}).get("analysis_epoch")
        or DEFAULT_ANALYSIS_EPOCH
    )


def _config_snapshot_path(cfg: dict) -> Path:
    """Path of the per-run config snapshot under
    ``data/<env>/config_snapshots/<YYYY-MM-DD>_<run_id>.yaml``.

    Computed deterministically from the cached run_id so every event
    in a run reports the same path. The file itself is written once
    at ``main()`` startup by :func:`_write_config_snapshot`."""
    env = _strategy_environment(cfg)
    rid = _run_id(env)
    # File name = <YYYY-MM-DD>_<run_id>.yaml. The date prefix lets
    # operators eyeball "today's snapshots" without parsing run_ids.
    day = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    base = _ledger_base_dir(cfg)
    return base / env / "config_snapshots" / f"{day}_{rid}.yaml"


def _write_config_snapshot(cfg: dict) -> Path | None:
    """Write the resolved cfg to ``_config_snapshot_path(cfg)`` if it
    doesn't already exist. Best-effort — returns None on failure so a
    snapshot mishap can't block startup."""
    try:
        path = _config_snapshot_path(cfg)
        if path.exists():
            return path
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            yaml.safe_dump(cfg, f, sort_keys=True)
        return path
    except Exception as e:
        LOG.warning("config snapshot write failed: %s", e)
        return None


class _LineBufferedFileHandler(logging.FileHandler):
    """FileHandler whose underlying file is opened with ``buffering=1``
    (line-buffered). The default ``logging.FileHandler`` block-
    buffers writes; in a long-running daemon with low log volume the
    buffer fills slowly and the file on disk looks frozen for
    minutes at a time, even when the process is actively logging.
    Live ops monitoring (and post-incident triage) need each record
    visible the instant it's emitted. Line buffering flushes on
    every newline, and every log record ends in ``\\n``."""

    def _open(self):
        return open(
            self.baseFilename,
            self.mode,
            buffering=1,  # line-buffered (text mode only)
            encoding=self.encoding or "utf-8",
            errors=self.errors,
        )


def setup_logging(cfg: dict) -> None:
    log_cfg = cfg.get("logging", {})
    level = getattr(logging, log_cfg.get("level", "INFO").upper())
    # Force stdout to flush per write so the watchdog stdout log
    # mirrors the strategy's logger in near-real-time.
    try:
        sys.stdout.reconfigure(line_buffering=True)
    except Exception:
        pass
    handlers: list[logging.Handler] = [logging.StreamHandler(sys.stdout)]
    if path := log_cfg.get("file"):
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        handlers.append(_LineBufferedFileHandler(path))
    # Phase 1.1: attach the redaction filter to every handler so no
    # log line (console or file) writes a raw API key / bearer token.
    redactor = _RedactingFilter()
    for h in handlers:
        h.addFilter(redactor)
    logging.basicConfig(
        level=level,
        format="%(asctime)s %(name)s %(levelname)s %(message)s",
        handlers=handlers,
        force=True,
    )
    # basicConfig with force=True replaces root handlers but does NOT
    # re-attach our filter to the root logger's *new* handlers if
    # something later calls basicConfig again. Be defensive: attach
    # the filter to the root logger itself too — that catches the
    # ``logger.handle()`` path regardless of which handler ends up
    # emitting the record.
    logging.getLogger().addFilter(redactor)


# Item 8 — gate-drift handshake. The reviewer's exact ask:
#
#   "either pin the expected prefilter hash or load the prefilter
#    config at strategy startup and compare the signal gates and
#    indicators."
#
# Auto-pinning is brittle (drifts silently); we go with the second
# option. At startup we open the prefilter yaml and assert that every
# signal_gates / indicators key has the same value on both sides.
# Any mismatch raises HandshakeMismatch so the operator notices on
# the very first tick.
class HandshakeMismatch(RuntimeError):
    """Raised when the strategy yaml's signal_gates / indicators
    don't match the prefilter yaml's. Means the EOD signal-fade
    re-evaluation would use thresholds the prefilter never applied
    when picking candidates."""


def verify_prefilter_handshake(
    cfg: dict,
    *,
    prefilter_yaml_path: str | Path | None = None,
) -> None:
    """Cross-check that the strategy and prefilter agree on signal
    thresholds and indicator windows. Item 8 (handshake): even with
    ``prefilter_handshake.expected_config_hash=null`` the operator
    gets a loud failure when the two yamls drift.

    The path is resolved as:
      1. ``cfg.prefilter_handshake.prefilter_yaml_path`` if set
      2. ``prefilter_yaml_path`` keyword (test override)
      3. a sibling file at ``strategies/scripts/bowaka_prefilter.yaml``
    Missing prefilter yaml → log a warning and return (don't fail
    just because someone moved files around).
    """
    handshake_cfg = cfg.get("prefilter_handshake") or {}
    path = (
        handshake_cfg.get("prefilter_yaml_path")
        or prefilter_yaml_path
        or (Path(__file__).resolve().parent / "bowaka_prefilter.yaml")
    )
    p = Path(path)
    if not p.exists():
        LOG.warning(
            "verify_prefilter_handshake: %s not found — skipping gate cross-check. "
            "Set cfg.prefilter_handshake.prefilter_yaml_path to enable.", p,
        )
        return

    with open(p) as f:
        prefilter_cfg = yaml.safe_load(f) or {}

    pf_signals = (prefilter_cfg.get("signals") or {})
    st_gates = (cfg.get("signal_gates") or {})
    pf_inds = (prefilter_cfg.get("indicators") or {})
    st_inds = (cfg.get("indicators") or {})

    drift: list[str] = []
    # Compare every key the strategy declares to the matching prefilter
    # value. Missing prefilter keys are also drift — the prefilter
    # wasn't gating on something the signal_fade exit re-checks.
    for k, st_v in st_gates.items():
        pf_v = pf_signals.get(k)
        if pf_v != st_v:
            drift.append(
                f"signal_gates.{k}: strategy={st_v!r} prefilter={pf_v!r}"
            )
    for k, st_v in st_inds.items():
        pf_v = pf_inds.get(k)
        if pf_v != st_v:
            drift.append(
                f"indicators.{k}: strategy={st_v!r} prefilter={pf_v!r}"
            )

    if drift:
        raise HandshakeMismatch(
            "strategy and prefilter configs disagree — signal-fade "
            "exits would use different thresholds than the entry "
            "prefilter:\n  " + "\n  ".join(drift)
            + "\nFix the drift in either yaml and restart."
        )
    LOG.info(
        "prefilter handshake verified: %d gates + %d indicator settings match",
        len(st_gates), len(st_inds),
    )


# ---------------------------------------------------------------- state I/O


def load_state(path: Path) -> State:
    if not path.exists():
        return blank_state()
    with open(path) as f:
        raw = json.load(f)
    # Fill defaults so old state files survive new field additions.
    base = blank_state()
    base.update(raw)
    return base  # type: ignore[return-value]


def save_state(state: State, path: Path) -> None:
    """Atomic write: ``.tmp`` → fsync → rename. Safe against crash mid-write."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    with open(tmp, "w") as f:
        json.dump(state, f, indent=2, sort_keys=True, default=str)
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, path)


def reset_for_new_session(
    state: State, today_iso: str, equity: float | None
) -> None:
    """Zero daily fields without touching open_positions or pending exits."""
    state["session_date"] = today_iso
    state["daily_pnl_baseline_equity"] = equity
    state["daily_pnl_tripped"] = False
    state["halt_skip_today"] = []
    # Post-closure rescreen daily counters/sets.
    state["entered_today"] = []
    state["daily_entries_count"] = 0
    state["rescreen_pending"] = False
    state["rescreens_today"] = 0
    state["post_closure_entries_today"] = 0
    # Phase 3.3 — daily-risk circuit-breaker state. These are
    # session-scoped — the block flag must NOT survive a session
    # boundary. (Mid-session restart preserves them, see Phase 3.7.)
    state["daily_stopouts_count"] = 0
    state["consecutive_stopouts_count"] = 0
    state["block_new_entries_today"] = False
    state["new_entries_blocked_reason"] = None
    state["daily_realized_pnl_strategy"] = 0.0
    state["daily_realized_pnl_bankroll_pct"] = 0.0
    # Phase 3: dedupe flags are per-day.
    state.pop("signal_fade_evaluated_for_date", None)
    state.pop("summary_written_for_date", None)
    state.pop("daily_marks_written_for_date", None)


# ---------------------------------------------------------------- session


_NYSE = mcal.get_calendar("NYSE")


def _to_eastern(now_utc: datetime) -> datetime:
    """Convert any tz-aware (or naive-treated-as-UTC) datetime to NY tz."""
    import pytz

    et = pytz.timezone("America/New_York")
    if now_utc.tzinfo is None:
        now_utc = now_utc.replace(tzinfo=timezone.utc)
    return now_utc.astimezone(et)


def is_in_session(
    now_utc: datetime,
    *,
    start: str = "09:30",
    end: str = "15:55",
) -> bool:
    """09:30–15:55 ET regular session, NYSE trading day. False on
    weekends, NYSE holidays, and outside the regular window."""
    et = _to_eastern(now_utc)
    sched = _NYSE.schedule(start_date=et.date(), end_date=et.date())
    if sched.empty:
        return False
    sh, sm = (int(x) for x in start.split(":"))
    eh, em = (int(x) for x in end.split(":"))
    et_minutes = et.hour * 60 + et.minute
    return (sh * 60 + sm) <= et_minutes <= (eh * 60 + em)


def is_signal_fade_window(now_utc: datetime, eval_time: str = "16:05") -> bool:
    """True at the configured EOD evaluation minute on a NYSE trading
    day. The minute granularity is intentional — the main loop only
    needs to fire signal-fade once per day; a state flag dedupes."""
    et = _to_eastern(now_utc)
    sched = _NYSE.schedule(start_date=et.date(), end_date=et.date())
    if sched.empty:
        return False
    eh, em = (int(x) for x in eval_time.split(":"))
    return et.hour == eh and et.minute == em


# ---------------------------------------------------------------- shutdown

_shutdown_requested = False


def _request_shutdown(signum, frame):  # noqa: ARG001 — signal signature
    global _shutdown_requested
    LOG.info("Signal %s received, requesting shutdown", signum)
    _shutdown_requested = True


def shutdown_requested() -> bool:
    return _shutdown_requested


def install_signal_handlers() -> None:
    signal.signal(signal.SIGTERM, _request_shutdown)
    signal.signal(signal.SIGINT, _request_shutdown)


# ---------------------------------------------------------------- candidates


class CandidatesError(Exception):
    """Base class for candidate-load failures."""


class CandidatesMissing(CandidatesError):
    pass


class CandidatesStaleError(CandidatesError):
    pass


class CandidatesHashMismatch(CandidatesError):
    pass


class CandidatesFeedMismatch(CandidatesError):
    """Phase 1.3: candidate file's ``data_feed`` does not match the
    operator-pinned ``prefilter_handshake.expected_data_feed``.

    Prevents the strategy from trading on candidates generated against
    the wrong tape (e.g. IEX-derived signals when an operator just
    flipped the YAML to SIP but did not regenerate the candidate
    file)."""


class CandidatesSchemaMismatch(CandidatesError):
    """Phase 1.3: candidate file's ``schema_version`` does not match
    the operator-pinned ``prefilter_handshake.expected_schema_version``.

    Catches stale candidate files from a pre-Phase-1.2 prefilter
    where the v2 provenance fields are missing."""


@dataclass
class Candidate:
    ticker: str
    close: float
    signal_strength: float
    # ISO 10383 MIC for /api/v2 instrument resolution. None when the
    # candidate file predates the venue-routing format (pre-Item-2);
    # callers fall back to ``cfg.sizing.default_venue_code`` in that
    # case so legacy candidate files keep working.
    venue_code: str | None = None
    exchange: str | None = None
    features: dict[str, Any] = field(default_factory=dict)
    # Phase 2.5 — instrument classification carried in from the
    # prefilter's schema-v2 candidate file. ``instrument_class``
    # defaults to None so legacy v1 candidate files (no class) still
    # load; ``eligible_for_bowaka_equity_bucket`` defaults to True
    # for the same reason. The strategy's select_entries enforces a
    # belt-and-suspenders check against this so a leveraged ETP that
    # somehow makes it through the prefilter (stale candidate file,
    # config relaxation) does not reach submit_entry.
    instrument_class: str | None = None
    eligible_for_bowaka_equity_bucket: bool = True


def _trading_days_between(d1_iso: str, d2_iso: str) -> int:
    """Count NYSE trading days strictly between two ISO dates inclusive
    of the start, exclusive of the end (i.e., how many trading days
    have passed)."""
    d1 = datetime.fromisoformat(d1_iso).date()
    d2 = datetime.fromisoformat(d2_iso).date() if isinstance(d2_iso, str) else d2_iso
    if d1 > d2:
        return 0
    sched = _NYSE.schedule(start_date=d1, end_date=d2)
    # Trading days behind: (today's index) - (as_of's index).
    if sched.empty:
        return 0
    # Number of trading days BETWEEN d1 and d2 (excluding d1 itself).
    return max(0, len(sched) - 1)


def load_candidates(
    path: Path | str,
    *,
    max_age_trading_days: int,
    expected_config_hash: str | None,
    today_et: date,
    expected_data_feed: str | None = None,
    expected_schema_version: int | None = None,
) -> list[Candidate]:
    """Load + validate the prefilter's candidates JSON.

    Validates ``as_of_date`` is at most ``max_age_trading_days`` *trading*
    days behind ``today_et`` (NYSE calendar). Validates ``config_hash``
    matches ``expected_config_hash`` when pinned. Returns the
    candidates list sorted by ``signal_strength`` descending.

    Phase 1.3 adds two fail-closed gates:

    * ``expected_data_feed`` — when set (typically ``"iex"`` or ``"sip"``)
      the payload's ``data_feed`` must match exactly. Mismatch raises
      :class:`CandidatesFeedMismatch` so the strategy refuses to trade
      on signals built against the wrong tape.
    * ``expected_schema_version`` — when set, the payload's
      ``schema_version`` must match. Mismatch raises
      :class:`CandidatesSchemaMismatch`.

    Both new gates are no-ops when ``None`` (default), preserving
    legacy behavior for operators who have not yet pinned the YAML.
    """
    p = Path(path)
    if not p.exists():
        raise CandidatesMissing(f"candidates file not found: {p}")
    with open(p) as f:
        payload = json.load(f)

    if expected_config_hash is not None:
        # v2 contract puts the full sha256 in ``config_hash`` and keeps
        # the legacy 8-hex form in ``config_hash_short``. Match either
        # so operators can pin whichever form they currently track.
        seen = payload.get("config_hash")
        seen_short = payload.get("config_hash_short")
        if seen != expected_config_hash and seen_short != expected_config_hash:
            raise CandidatesHashMismatch(
                f"config_hash mismatch: got {seen!r} / short={seen_short!r}, "
                f"expected {expected_config_hash!r}"
            )

    if expected_schema_version is not None:
        seen_schema = payload.get("schema_version")
        if seen_schema != expected_schema_version:
            raise CandidatesSchemaMismatch(
                f"schema_version mismatch: got {seen_schema!r}, "
                f"expected {expected_schema_version!r}"
            )

    if expected_data_feed is not None:
        seen_feed = payload.get("data_feed")
        if seen_feed != expected_data_feed:
            raise CandidatesFeedMismatch(
                f"data_feed mismatch: got {seen_feed!r}, "
                f"expected {expected_data_feed!r}"
            )

    as_of_iso = payload.get("as_of_date")
    if as_of_iso is None:
        raise CandidatesStaleError("candidates missing as_of_date")
    age = _trading_days_between(as_of_iso, today_et.isoformat())
    if age > max_age_trading_days:
        raise CandidatesStaleError(
            f"candidates {age} trading days behind today (max={max_age_trading_days})"
        )

    out: list[Candidate] = []
    for row in payload.get("candidates", []):
        # Phase 2.5: hydrate instrument-class fields when present.
        # Missing fields default to safe values (None / True) so
        # pre-v2 candidate files still load — the select_entries
        # gate treats those as operating equity by convention.
        out.append(Candidate(
            ticker=row["ticker"],
            close=float(row["close"]),
            signal_strength=float(row.get("signal_strength") or 0.0),
            venue_code=row.get("venue_code") or None,
            exchange=row.get("exchange") or None,
            features={k: row.get(k) for k in (
                "rvol", "atr_pct", "range_expansion", "gap_pct",
                "close_location", "ema_distance", "ema_slope",
                "avg_dollar_volume",
            )},
            instrument_class=row.get("instrument_class") or None,
            eligible_for_bowaka_equity_bucket=bool(
                row.get("eligible_for_bowaka_equity_bucket", True)
            ),
        ))
    out.sort(key=lambda c: c.signal_strength, reverse=True)
    return out


# ---------------------------------------------------------------- http client


def make_http_client(
    base_url: str,
    timeout: float = 15.0,
    transport: httpx.BaseTransport | None = None,
) -> httpx.Client:
    """Plain httpx.Client. Tests pass an httpx.MockTransport."""
    kwargs: dict[str, Any] = {
        "base_url": base_url,
        "timeout": timeout,
    }
    if transport is not None:
        kwargs["transport"] = transport
    return httpx.Client(**kwargs)


def _api_headers(api_key: str) -> dict[str, str]:
    return {"X-API-KEY": api_key, "Content-Type": "application/json"}


# ---------------------------------------------------------------- equity


def fetch_equity(http: httpx.Client, api_key: str) -> float:
    """GET /api/v2/balances and return the equity figure.

    Returns ``equity`` when the broker adapter populates it; falls back
    to ``cash`` so India brokers (which have no equity field in the
    balance response) still produce a usable number for sizing.
    """
    # Phase 1.1: header-only auth on GET. The v2 lane reads X-API-KEY
    # (see restx_api/v2/_auth.py); the redundant ?apikey= query string
    # used to land the secret in nginx / proxy access logs.
    r = http.get("/api/v2/balances", headers=_api_headers(api_key))
    r.raise_for_status()
    body = r.json().get("data") or {}
    bal = body.get("balance") or body.get("balances") or {}
    if isinstance(bal, dict):
        if "equity" in bal and bal["equity"] is not None:
            return float(bal["equity"])
        if "cash" in bal and bal["cash"] is not None:
            return float(bal["cash"])
    raise RuntimeError(f"could not parse equity from /api/v2/balances response: {body!r}")


def fetch_cash(http: httpx.Client, api_key: str) -> float:
    """GET /api/v2/balances and return only the cash figure.

    Used at bankroll initialization when ``initial.pct_of_cash`` is
    set — we want the available cash, not total equity (which would
    include open-position market value, double-counting the bankroll
    against itself).
    """
    # Phase 1.1: header-only auth on GET (see fetch_equity comment).
    r = http.get("/api/v2/balances", headers=_api_headers(api_key))
    r.raise_for_status()
    body = r.json().get("data") or {}
    bal = body.get("balance") or body.get("balances") or {}
    if isinstance(bal, dict) and bal.get("cash") is not None:
        return float(bal["cash"])
    raise RuntimeError(
        f"could not parse cash from /api/v2/balances response: {body!r}"
    )


# ---------------------------------------------------------------- bankroll


class BankrollConfigError(Exception):
    """Operator-facing error for malformed cfg.bankroll. Raising at
    init is intentional — the safe behavior is "refuse to run" rather
    than "silently fall back to broker equity and over-size every
    trade by 10×"."""


def _bankroll_cfg(cfg: dict) -> dict | None:
    """Return cfg.bankroll dict when the feature is enabled, else None
    (so existing legacy callers continue to use broker equity)."""
    bk = cfg.get("bankroll")
    if not bk:
        return None
    return bk


def _validate_bankroll_cfg(bk_cfg: dict) -> None:
    """Strict-mode validation. Exactly one of pct_of_cash / fixed_
    dollars must be set; values must be non-negative; cap_dollars (when
    set) must be > initial."""
    initial = bk_cfg.get("initial") or {}
    pct = initial.get("pct_of_cash")
    fixed = initial.get("fixed_dollars")
    if pct is None and fixed is None:
        raise BankrollConfigError(
            "bankroll.initial requires exactly one of "
            "pct_of_cash or fixed_dollars; both are null"
        )
    if pct is not None and fixed is not None:
        raise BankrollConfigError(
            "bankroll.initial: set EXACTLY one of pct_of_cash or "
            "fixed_dollars; got both"
        )
    if pct is not None:
        try:
            pct_f = float(pct)
        except (TypeError, ValueError):
            raise BankrollConfigError(
                f"bankroll.initial.pct_of_cash must be numeric; got {pct!r}"
            )
        if pct_f <= 0 or pct_f > 1:
            raise BankrollConfigError(
                f"bankroll.initial.pct_of_cash must be in (0, 1]; got {pct_f}"
            )
    if fixed is not None:
        try:
            fixed_f = float(fixed)
        except (TypeError, ValueError):
            raise BankrollConfigError(
                f"bankroll.initial.fixed_dollars must be numeric; got {fixed!r}"
            )
        if fixed_f <= 0:
            raise BankrollConfigError(
                f"bankroll.initial.fixed_dollars must be > 0; got {fixed_f}"
            )
    cap = bk_cfg.get("cap_dollars")
    if cap is not None:
        try:
            cap_f = float(cap)
        except (TypeError, ValueError):
            raise BankrollConfigError(
                f"bankroll.cap_dollars must be numeric or null; got {cap!r}"
            )
        if cap_f <= 0:
            raise BankrollConfigError(
                f"bankroll.cap_dollars must be > 0 when set; got {cap_f}"
            )

    # daily_allocation validation. Only checked when enabled — the
    # ``days`` override may be null, in which case we'll defer to
    # cfg.exits.max_hold_days at sizing time (which must be > 0; the
    # exits block has its own validation, so we don't re-check here).
    da = bk_cfg.get("daily_allocation") or {}
    if da.get("enabled"):
        days = da.get("days")
        if days is not None:
            try:
                days_int = int(days)
            except (TypeError, ValueError):
                raise BankrollConfigError(
                    f"bankroll.daily_allocation.days must be an integer "
                    f"or null; got {days!r}"
                )
            if days_int <= 0:
                raise BankrollConfigError(
                    f"bankroll.daily_allocation.days must be > 0; "
                    f"got {days_int}"
                )


def initialize_bankroll(
    state: State,
    cfg: dict,
    http: httpx.Client,
    api_key: str,
    *,
    state_path: Path,
    now_utc: datetime | None = None,
) -> bool:
    """Seed or re-seed the bankroll envelope based on cfg.bankroll.

    Returns True when a (re-)init happened, False when no action was
    needed (feature disabled, or persisted state matches the YAML's
    reset_token already).

    Init triggers:
    - State has no bankroll dict (first launch with the feature on).
    - cfg.bankroll.reset_token differs from
      state.bankroll.last_reset_token (operator-driven reset).

    Init can fail two ways:
    - cfg validation raises BankrollConfigError — the operator must
      fix the YAML. Strategy refuses to start.
    - pct_of_cash mode requires fetching cash from the broker; a
      network failure here also raises so the strategy doesn't proceed
      with a half-initialized bankroll. Next launch retries.

    Cap is applied at init too: if initial > cap, we clamp at cap and
    note the clamp in initial_source.
    """
    bk_cfg = _bankroll_cfg(cfg)
    if bk_cfg is None:
        return False
    _validate_bankroll_cfg(bk_cfg)

    yaml_token = str(bk_cfg.get("reset_token", "") or "")
    state_bk = state.get("bankroll") or {}
    state_token = str(state_bk.get("last_reset_token", "") or "")
    if state_bk and yaml_token == state_token:
        # Already initialized at this token — surface the current
        # state so operators have a one-line summary on every restart
        # (instead of having to grep prior logs / open state.json).
        cap = bk_cfg.get("cap_dollars")
        LOG.info(
            "bankroll persisted: current=$%.2f (high_water=$%.2f, "
            "source: %s, cap=%s, token=%r)",
            float(state_bk.get("current_dollars", 0.0)),
            float(state_bk.get("high_water_mark", 0.0)),
            state_bk.get("initial_source", "?"),
            f"${float(cap):.2f}" if cap is not None else "none",
            yaml_token,
        )
        return False  # already initialized at the current token

    initial = bk_cfg.get("initial") or {}
    pct = initial.get("pct_of_cash")
    fixed = initial.get("fixed_dollars")
    if fixed is not None:
        amount = float(fixed)
        source = f"fixed_dollars={fixed}"
    else:
        cash = fetch_cash(http, api_key)
        amount = float(cash) * float(pct)
        source = f"pct_of_cash={pct} * cash={cash:.2f}"

    cap = bk_cfg.get("cap_dollars")
    if cap is not None and amount > float(cap):
        amount = float(cap)
        source += f" (initial clamped to cap={cap})"

    iso = (now_utc or datetime.now(timezone.utc)).isoformat()
    state["bankroll"] = {
        "current_dollars": amount,
        "initialized_at": iso,
        "initial_source": source,
        "high_water_mark": amount,
        "last_reset_token": yaml_token,
    }
    save_state(state, state_path)
    LOG.info(
        "bankroll initialized: $%.2f (source: %s, cap=%s, token=%r)",
        amount, source,
        f"${float(cap):.2f}" if cap is not None else "none",
        yaml_token,
    )
    return True


def apply_realized_pnl_to_bankroll(
    state: State, cfg: dict, realized_pnl: float,
) -> None:
    """Update bankroll after a closure. Caller is responsible for
    save_state (close_position already saves at the end).

    - Cap: realized profits that push above cap_dollars are forfeit.
    - Floor: realized losses can't drive bankroll negative; clamp at 0.
    - high_water_mark: monotonic. Useful for postmortem (max bankroll
      ever reached this lifetime).

    No-op when the bankroll feature is disabled (state lacks the dict).
    """
    state_bk = state.get("bankroll")
    if not state_bk:
        return
    bk_cfg = _bankroll_cfg(cfg) or {}
    cur = float(state_bk.get("current_dollars", 0.0))
    new = cur + float(realized_pnl)
    cap = bk_cfg.get("cap_dollars")
    if cap is not None and new > float(cap):
        new = float(cap)
    if new < 0.0:
        new = 0.0
    state_bk["current_dollars"] = new
    state_bk["high_water_mark"] = max(
        new, float(state_bk.get("high_water_mark", new))
    )
    state["bankroll"] = state_bk


def get_bankroll_dollars(state: State, fallback_equity: float) -> float:
    """Return the full bankroll envelope value (the un-sliced number).

    Used as the gross-exposure-cap basis. Falls back to broker equity
    when the bankroll feature is disabled.
    """
    state_bk = state.get("bankroll")
    if state_bk and "current_dollars" in state_bk:
        return float(state_bk["current_dollars"])
    return float(fallback_equity)


def get_sizing_basis(
    state: State,
    fallback_equity: float,
    cfg: dict | None = None,
) -> float:
    """Return the per-trade sizing basis: the dollar number multiplied
    by per_trade_pct to compute each individual trade's budget.

    By default this is the full bankroll (or fallback equity). When
    cfg.bankroll.daily_allocation.enabled is true, the basis is sliced
    down to bankroll / N, where N is either
    cfg.bankroll.daily_allocation.days or cfg.exits.max_hold_days when
    the override is null. The gross-exposure cap continues to use the
    full bankroll via :func:`get_bankroll_dollars`, so total cumulative
    exposure is bounded by max_gross_exposure_pct × bankroll, not by
    the daily slice.

    A misconfigured daily_allocation (enabled but no usable day count)
    falls back to the full bankroll with a logged warning rather than
    raising — operators editing YAML live shouldn't trip a crash.
    """
    bankroll = get_bankroll_dollars(state, fallback_equity)
    if cfg is None:
        return bankroll
    da = ((cfg.get("bankroll") or {}).get("daily_allocation") or {})
    if not da.get("enabled"):
        return bankroll
    days = da.get("days")
    if days is None:
        days = (cfg.get("exits") or {}).get("max_hold_days")
    try:
        days_int = int(days) if days is not None else 0
    except (TypeError, ValueError):
        days_int = 0
    if days_int <= 0:
        LOG.warning(
            "bankroll.daily_allocation enabled but no usable day count "
            "(days=%r, exits.max_hold_days=%r); falling back to full bankroll",
            da.get("days"), (cfg.get("exits") or {}).get("max_hold_days"),
        )
        return bankroll
    return bankroll / days_int


# ---------------------------------------------------------------- sizing


def compute_qty(
    equity: float,
    close_price: float,
    per_trade_pct: float,
    max_per_trade_dollars: float | None = None,
    *,
    avg_dollar_volume: float | None = None,
    max_position_as_adv_frac: float | None = None,
    per_trade_dollars_override: float | None = None,
) -> int:
    """floor(min(equity*pct, abs_cap, adv_cap) / close). Whole shares
    only — bracket orders reject fractional at Alpaca. Returns 0 when
    the target dollars don't cover one share (caller skips).

    The ADV cap (Item 3 / expert review) is the strategy's stated
    capacity edge. Without it a $1M account at 10% per-trade puts $100k
    into a name with $250k ADV — a 40% participation rate that
    contradicts the capacity-limited thesis. Pass both
    ``avg_dollar_volume`` (from the candidate features) and
    ``max_position_as_adv_frac`` (from ``cfg.risk``) to enable the cap.

    ``per_trade_dollars_override``: when set, replaces ``equity *
    per_trade_pct`` as the starting target. The
    sizing.equal_slice_per_position mode uses this to apportion the
    bankroll evenly across max_concurrent_positions slots, so each
    trade is bankroll/N regardless of the configured per_trade_pct.
    The other caps (max_per_trade_dollars, ADV cap) still apply.
    """
    if per_trade_dollars_override is not None:
        target = float(per_trade_dollars_override)
    else:
        target = equity * per_trade_pct
    if max_per_trade_dollars is not None:
        target = min(target, max_per_trade_dollars)
    if (
        avg_dollar_volume is not None
        and max_position_as_adv_frac is not None
        and avg_dollar_volume > 0
        and max_position_as_adv_frac > 0
    ):
        target = min(target, avg_dollar_volume * max_position_as_adv_frac)
    if close_price <= 0 or target <= 0:
        return 0
    return int(math.floor(target / close_price))


# ---------------------------------------------------------------- Phase 6.2 — risk-per-trade + ADV tier caps


def adv_tier_cap(
    avg_dollar_volume: float | None, cfg: dict,
) -> tuple[bool, float]:
    """Resolve the position dollar cap for ``avg_dollar_volume`` under
    the tiered ADV policy. Returns ``(allowed, max_position_dollars)``.

    Behavior:
      * If ``risk.adv_tier_caps`` is missing or empty: falls back to
        the legacy flat ``risk.max_position_as_adv_frac`` (back-
        compat). Returns ``(True, adv * flat_frac)`` or
        ``(True, 0.0)`` if no flat fraction is configured.
      * If ``risk.adv_tier_caps`` is non-empty: walks tiers top-to-
        bottom (YAML order is meaningful — the operator-authored
        sequence is the policy). The first tier whose
        ``max_adv_dollars`` is None (the catch-all) or >=
        ``avg_dollar_volume`` matches. If that tier has
        ``reject_if_below: true`` returns ``(False, 0.0)``;
        otherwise returns
        ``(True, adv * tier['max_position_as_adv_frac'])``.
      * If ``avg_dollar_volume`` is None or <= 0: returns
        ``(False, 0.0)`` — we cannot size against unknown liquidity.

    Boundary semantics: a stock at exactly the tier's
    ``max_adv_dollars`` threshold is included in that tier (inclusive
    ``<=`` comparison). Comments in the YAML use "below $X" as a
    label; the implementation uses ``<=``, which matches a candidate
    at exactly $X to the next tier up.
    """
    if avg_dollar_volume is None or float(avg_dollar_volume) <= 0:
        return False, 0.0

    adv = float(avg_dollar_volume)
    tiers = ((cfg.get("risk") or {}).get("adv_tier_caps") or [])

    if not tiers:
        flat = (cfg.get("risk") or {}).get("max_position_as_adv_frac")
        if flat is None:
            return True, 0.0
        return True, adv * float(flat)

    for tier in tiers:
        max_adv = tier.get("max_adv_dollars")
        if max_adv is None or adv <= float(max_adv):
            if tier.get("reject_if_below"):
                return False, 0.0
            frac = tier.get("max_position_as_adv_frac")
            if frac is None:
                return True, 0.0
            return True, adv * float(frac)

    # Defensive: if no tier matched (shouldn't happen with a catch-
    # all null tier), reject conservatively rather than over-sizing.
    return False, 0.0


def compute_risk_sized_qty(
    entry_price: float,
    stop_pct: float,
    avg_dollar_volume: float | None,
    cfg: dict,
) -> int:
    """Phase 6.2 — qty sized to bound the worst-case planned loss at
    ``sizing.target_risk_dollars``.

    Math (Report §8.8):
      loss_per_share = entry_price * (stop_pct + expected_stop_slippage_pct)
      base_qty       = floor(target_risk_dollars / loss_per_share)

    Then we apply:
      * ``sizing.max_per_trade_dollars`` (notional cap)
      * ``risk.adv_tier_caps`` (or legacy ``max_position_as_adv_frac``)
      * ``sizing.min_order_notional`` (reject too-small orders)

    Returns the integer qty (0 means "skip the entry").
    """
    sizing = cfg.get("sizing") or {}
    risk_cfg = cfg.get("risk") or {}
    if entry_price <= 0 or stop_pct <= 0:
        return 0
    target_risk = float(sizing.get("target_risk_dollars") or 0)
    if target_risk <= 0:
        return 0
    slip = float(risk_cfg.get("expected_stop_slippage_pct") or 0.0)
    loss_per_share = float(entry_price) * (float(stop_pct) + slip)
    if loss_per_share <= 0:
        return 0
    base_qty = int(math.floor(target_risk / loss_per_share))
    if base_qty <= 0:
        return 0
    notional = base_qty * float(entry_price)

    # Per-trade notional cap.
    max_per_trade = sizing.get("max_per_trade_dollars")
    if max_per_trade is not None:
        cap_notional = float(max_per_trade)
        if notional > cap_notional:
            base_qty = int(math.floor(cap_notional / float(entry_price)))
            notional = base_qty * float(entry_price)
    if base_qty <= 0:
        return 0

    # ADV tier cap (tiered) takes precedence over legacy
    # max_position_as_adv_frac when adv_tier_caps is set.
    # ADV-tier-caps update: ``adv_tier_cap`` now returns ``(True, 0.0)``
    # only when neither tiers nor a flat fallback frac is configured
    # — treat that as "no cap" and leave base_qty unchanged. A
    # positive cap clamps base_qty down; ``(False, 0.0)`` rejects.
    allowed, adv_cap = adv_tier_cap(avg_dollar_volume, cfg)
    if not allowed:
        return 0
    if adv_cap > 0:
        adv_qty = int(math.floor(float(adv_cap) / float(entry_price)))
        base_qty = min(base_qty, max(adv_qty, 0))
    if base_qty <= 0:
        return 0

    notional = base_qty * float(entry_price)
    min_notional = sizing.get("min_order_notional")
    if min_notional is not None and notional < float(min_notional):
        return 0
    return base_qty


def _equal_slice_fraction(cfg: dict) -> float:
    """Resolve the equal-slice bankroll fraction.

    Resolution order:
    1. Explicit ``sizing.equal_slice_bankroll_fraction`` when set
       in (0, 1].
    2. AUTO-COUPLE to ``risk.max_gross_exposure_pct`` when the
       explicit field is null. This pins per-trade × max_concurrent
       to the gross-exposure cap so the cap can't silently block
       the last few slots.
    3. ``1.0`` (full bankroll) when both are unset.

    Invalid values (non-numeric, out of range) log a warning and
    fall back to 1.0 — fail-soft so a typo at startup doesn't kill
    sizing entirely.
    """
    sizing_cfg = cfg.get("sizing") or {}
    risk_cfg = cfg.get("risk") or {}

    explicit = sizing_cfg.get("equal_slice_bankroll_fraction")
    if explicit is not None:
        try:
            f = float(explicit)
        except (TypeError, ValueError):
            LOG.warning(
                "sizing.equal_slice_bankroll_fraction=%r non-numeric; "
                "falling back to auto-couple",
                explicit,
            )
        else:
            if 0.0 < f <= 1.0:
                return f
            LOG.warning(
                "sizing.equal_slice_bankroll_fraction=%r out of (0, 1]; "
                "falling back to auto-couple",
                explicit,
            )

    auto = risk_cfg.get("max_gross_exposure_pct")
    if auto is not None:
        try:
            f = float(auto)
        except (TypeError, ValueError):
            return 1.0
        if 0.0 < f <= 1.0:
            return f
    return 1.0


def _per_trade_dollars_for_slate(
    state: State, cfg: dict, fallback_equity: float,
) -> float | None:
    """Return the per-trade dollar target when
    sizing.equal_slice_per_position is enabled.

    Math: ``fraction × bankroll / max_concurrent_positions``, where
    ``fraction`` resolves via :func:`_equal_slice_fraction` —
    explicit override, then auto-coupled to max_gross_exposure_pct,
    then 1.0. So with bankroll=$90k, max_concurrent=18, and
    max_gross_exposure_pct=0.80:
        per_trade = 0.80 × $90,000 / 18 = $4,000
    Each $1 of bankroll growth scales per_trade by
    ``fraction / max_concurrent``.

    Falls back to None (and the caller's per_trade_pct path) when:
    - The toggle is off.
    - max_concurrent_positions is missing, zero, or negative
      (misconfigured — we log a warning rather than divide by zero).
    """
    sizing_cfg = cfg.get("sizing") or {}
    if not sizing_cfg.get("equal_slice_per_position"):
        return None
    n = sizing_cfg.get("max_concurrent_positions")
    try:
        n_int = int(n) if n is not None else 0
    except (TypeError, ValueError):
        n_int = 0
    if n_int <= 0:
        LOG.warning(
            "sizing.equal_slice_per_position enabled but "
            "max_concurrent_positions=%r; falling back to per_trade_pct",
            n,
        )
        return None
    bankroll = get_bankroll_dollars(state, fallback_equity)
    fraction = _equal_slice_fraction(cfg)
    return (fraction * bankroll) / n_int


def current_gross_exposure(
    open_positions: dict[str, dict[str, Any]],
    latest_prices: dict[str, float],
) -> float:
    total = 0.0
    for ticker, pos in open_positions.items():
        qty = float(pos.get("qty") or 0)
        price = latest_prices.get(ticker)
        if price is None:
            price = pos.get("entry_price")
        if price is None:
            continue
        total += qty * float(price)
    return total


# ---------------------------------------------------------------- entry


@dataclass
class Entry:
    ticker: str
    qty: int
    close_price: float
    venue_code: str
    candidate: Candidate
    # Captured for the ``opened`` jsonl record so the analyst can see
    # the sizing rationale at the moment of submission. None when the
    # entry was constructed by older callers / tests that didn't supply
    # it; the opened-record writer falls back gracefully.
    equity_at_entry: float | None = None


# ---------------------------------------------------------------- Phase 5.2 — shadow controls
#
# When the paper-mode profile relaxes daily_loss_pct,
# max_gross_exposure_pct, max_total_entries_per_day, etc., the
# stricter thresholds those flags WOULD have applied get echoed as
# shadow_controls in every entry_decision event. The flags are not
# enforced — purely a research artifact so an operator can see how
# the live system would have behaved under tighter discipline
# without rerunning the data.


def _shadow_daily_loss(state: State, cfg: dict, threshold_pct: float) -> bool:
    """True when today's realized PnL fraction is at or below -threshold."""
    bk_basis = float(
        (state.get("bankroll") or {}).get("current_dollars") or 0.0
    )
    if bk_basis <= 0:
        return False
    pnl = float(state.get("daily_realized_pnl_strategy") or 0.0)
    return (pnl / bk_basis) <= -abs(float(threshold_pct))


def _shadow_gross_exposure(
    state: State, cfg: dict, projected_gross_dollars: float,
    threshold_pct: float,
) -> bool:
    """True when adding the candidate would push gross exposure
    above ``threshold_pct`` of the bankroll basis."""
    bk_basis = float(
        (state.get("bankroll") or {}).get("current_dollars") or 0.0
    )
    if bk_basis <= 0:
        return False
    return (float(projected_gross_dollars) / bk_basis) > float(threshold_pct)


def _shadow_consecutive_stopouts(state: State, *, threshold: int) -> bool:
    return int(
        state.get("consecutive_stopouts_count") or 0
    ) >= int(threshold)


def compute_shadow_controls(
    state: State, cfg: dict, *, candidate_notional: float,
    is_stopout_day: bool, current_gross_exposure_dollars: float,
    entries_today: int,
) -> dict[str, bool]:
    """Phase 5.2 — compute what would-have-been-blocked under
    stricter rules. Returns a dict suitable for embedding in an
    entry_decision payload. Read-only; never mutates state."""
    projected_gross = float(current_gross_exposure_dollars) + float(candidate_notional)
    return {
        "would_block_daily_loss_1pct":
            _shadow_daily_loss(state, cfg, 0.01),
        "would_block_daily_loss_3pct":
            _shadow_daily_loss(state, cfg, 0.03),
        "would_block_gross_exposure_40pct":
            _shadow_gross_exposure(state, cfg, projected_gross, 0.40),
        "would_block_max_entries_4":  entries_today >= 4,
        "would_block_max_entries_10": entries_today >= 10,
        "would_block_after_2_stopouts":
            _shadow_consecutive_stopouts(state, threshold=2),
        "paper_mode_hard_block_applied": False,
    }


def select_entries(
    candidates: list[Candidate],
    state: State,
    *,
    equity: float,
    latest_prices: dict[str, float],
    cfg: dict,
    kill_state: KillLevel,
    entry_trigger: str = "session_open",
    remaining_entries_budget: int | None = None,
    gross_cap_basis: float | None = None,
) -> list[Entry]:
    """Walk candidates in signal_strength order, applying the entry
    gates from the architecture decisions. Returns the slate of
    accepted entries (bounded by max_concurrent_positions, gross
    exposure, and — when set — the daily total-entry cap).

    ``entry_trigger`` records why this pass ran (``"session_open"`` or
    ``"post_closure_rescreen"``) and is passed through to the position
    record so analytics can split the two populations.

    ``remaining_entries_budget``: when provided, caps the slate to at
    most this many entries. The post-closure rescreen uses this to
    enforce ``risk.max_total_entries_per_day`` accounting for entries
    already submitted earlier in the day.

    ``gross_cap_basis``: optional override for the gross-exposure cap
    calculation. When None, the cap is computed against ``equity``
    (back-compat). When set (typically to the FULL bankroll when
    ``equity`` is a per-day slice), the cap uses this number instead,
    decoupling per-trade size from the cumulative-exposure limit.
    """
    sizing_cfg = cfg["sizing"]
    risk_cfg = cfg["risk"]
    # Phase 1.4: slate-wide blocks emit ONE synthetic entry_decision
    # event (per the audit prompt) rather than fanning out across
    # every candidate. The rationale is captured in ``reason`` and
    # the slate size in the payload.
    if state.get("daily_pnl_tripped"):
        if candidates:
            emit_entry_decision_rejected(
                cfg, candidate=candidates[0], state=state,
                reason="daily_pnl_tripped",
                entry_trigger=entry_trigger,
                candidate_rank=0,
            )
        return []
    if kill_state in (KillLevel.L1_NEW, KillLevel.L2_SOFT, KillLevel.L3_HARD):
        if candidates:
            emit_entry_decision_rejected(
                cfg, candidate=candidates[0], state=state,
                reason="kill_switch",
                entry_trigger=entry_trigger,
                candidate_rank=0,
            )
        return []
    # Phase 3 will populate ``block_new_entries_today`` via the
    # circuit-breaker code; the gate below treats that flag as
    # slate-wide too.
    if state.get("block_new_entries_today"):
        if candidates:
            emit_entry_decision_rejected(
                cfg, candidate=candidates[0], state=state,
                reason="blocked_by_daily_risk",
                entry_trigger=entry_trigger,
                candidate_rank=0,
            )
        return []

    max_concurrent = int(sizing_cfg["max_concurrent_positions"])
    per_trade_pct = float(sizing_cfg["per_trade_pct"])
    max_per_trade_abs = risk_cfg.get("max_per_trade_dollars")
    # Item 3 / ADV-tier-caps: ADV participation cap is now resolved
    # per-candidate via :func:`adv_tier_cap` (handles both the
    # tiered policy AND the legacy flat ``max_position_as_adv_frac``
    # back-compat fallback). The pre-loop lookup of the flat frac is
    # no longer needed — the helper reads ``cfg`` directly.

    gross_basis = float(gross_cap_basis) if gross_cap_basis is not None else equity
    pct_cap = float(risk_cfg.get("max_gross_exposure_pct") or 0.0) * gross_basis
    abs_cap = risk_cfg.get("max_gross_exposure_dollars")
    gross_cap = abs_cap if abs_cap is not None else pct_cap

    open_positions = state.get("open_positions") or {}
    halt_skip = set(state.get("halt_skip_today") or [])
    # Same-day re-entry block: never re-enter a name that already had a
    # submitted entry today, regardless of how it exited. Without this
    # the rescreen path would happily re-buy a stock that just stopped
    # out an hour ago.
    entered_today = set(state.get("entered_today") or [])

    selected: list[Entry] = []
    running_gross = current_gross_exposure(open_positions, latest_prices)
    open_count = len(open_positions)
    # Equal-slice mode (sizing.equal_slice_per_position): override the
    # per-trade dollar target with bankroll / max_concurrent_positions.
    # Computed once per slate so every entry in this pass uses the
    # same target.
    per_trade_dollars_override = _per_trade_dollars_for_slate(
        state, cfg, fallback_equity=equity,
    )

    daily_cap_v = risk_cfg.get("max_total_entries_per_day")
    daily_cap_int = int(daily_cap_v) if daily_cap_v is not None else None
    daily_count_v = int(state.get("daily_entries_count", 0))

    for rank, cand in enumerate(candidates, start=1):
        # Phase 5.2 — shadow controls. Computed per-candidate so the
        # snapshot reflects "did THIS candidate cross would-block-
        # gross-exposure-40pct?". Pure read of state; never mutates.
        cand_notional = float(cand.close or 0.0) * float(
            per_trade_dollars_override or 0.0
        ) if per_trade_dollars_override else 0.0
        try:
            shadow = compute_shadow_controls(
                state, cfg,
                candidate_notional=cand_notional,
                is_stopout_day=False,
                current_gross_exposure_dollars=running_gross,
                entries_today=daily_count_v + len(selected),
            )
        except Exception:
            shadow = None

        # Phase 1.4: helper closure for rejection emission with shared
        # candidate-rank threading.
        def _reject(reason: str, qty: int | None = None,
                    _sh=shadow) -> None:
            emit_entry_decision_rejected(
                cfg, candidate=cand, state=state,
                reason=reason,
                entry_trigger=entry_trigger,
                candidate_rank=rank,
                qty=qty,
                venue_code=(cand.venue_code or sizing_cfg.get("default_venue_code")),
                shadow_controls=_sh,
            )

        if cand.ticker in halt_skip:
            _reject("halt_skip")
            continue
        if cand.ticker in open_positions:
            _reject("already_held")
            continue
        if cand.ticker in entered_today:
            _reject("already_entered_today")
            continue
        # Phase 2.5 — strategy-side belt-and-suspenders. The prefilter
        # already drops leveraged ETPs / ETNs when its
        # instrument_rules.<bucket>.action is "exclude", but stale
        # candidate files or future relaxation must not let one slip
        # through. ``None`` (legacy v1 candidate file) is treated as
        # operating_equity by convention so we don't break old runs.
        if cand.instrument_class is not None and cand.instrument_class != "operating_equity":
            _reject("excluded_instrument_class")
            continue
        if open_count + len(selected) >= max_concurrent:
            # Concurrent-cap is a slate-truncation reason; emit for
            # this candidate and every remaining one so total emissions
            # == total candidates considered (audit-prompt §1.4).
            _reject("concurrent_cap")
            for tail_rank, tail in enumerate(candidates[rank:], start=rank + 1):
                emit_entry_decision_rejected(
                    cfg, candidate=tail, state=state,
                    reason="concurrent_cap",
                    entry_trigger=entry_trigger,
                    candidate_rank=tail_rank,
                    venue_code=(tail.venue_code or sizing_cfg.get("default_venue_code")),
                )
            break
        if (
            remaining_entries_budget is not None
            and len(selected) >= int(remaining_entries_budget)
        ):
            _reject("daily_entry_cap")
            for tail_rank, tail in enumerate(candidates[rank:], start=rank + 1):
                emit_entry_decision_rejected(
                    cfg, candidate=tail, state=state,
                    reason="daily_entry_cap",
                    entry_trigger=entry_trigger,
                    candidate_rank=tail_rank,
                    venue_code=(tail.venue_code or sizing_cfg.get("default_venue_code")),
                )
            break
        if (
            daily_cap_int is not None
            and (daily_count_v + len(selected)) >= daily_cap_int
        ):
            _reject("daily_entry_cap")
            for tail_rank, tail in enumerate(candidates[rank:], start=rank + 1):
                emit_entry_decision_rejected(
                    cfg, candidate=tail, state=state,
                    reason="daily_entry_cap",
                    entry_trigger=entry_trigger,
                    candidate_rank=tail_rank,
                    venue_code=(tail.venue_code or sizing_cfg.get("default_venue_code")),
                )
            break
        adv = cand.features.get("avg_dollar_volume") if cand.features else None
        adv_f = float(adv) if adv is not None else None

        # ADV-tier-caps integration: resolve the tier-derived dollar
        # cap (or the legacy flat cap, via adv_tier_cap's fallback).
        # ``allowed=False`` means the candidate is rejected outright —
        # either ADV is unknown / zero, or the thinnest tier with
        # ``reject_if_below: true`` matched. ``adv_cap_dollars`` is
        # translated back to a per-candidate fraction so the existing
        # ``compute_qty(max_position_as_adv_frac=...)`` parameter
        # consumes it without a signature change.
        adv_allowed, adv_cap_dollars = adv_tier_cap(adv_f, cfg)
        if not adv_allowed:
            LOG.info(
                "adv_tier_caps: %s rejected (adv=%s)",
                cand.ticker, adv_f,
            )
            _reject("adv_tier_reject", qty=0)
            continue
        effective_adv_frac = (
            (adv_cap_dollars / adv_f)
            if (adv_f and adv_f > 0 and adv_cap_dollars > 0)
            else None
        )

        # Phase 6.2 — branch on sizing_mode. risk_per_trade caps the
        # planned dollar loss; equal_slice keeps the legacy
        # bankroll/N notional math. compute_risk_sized_qty re-consults
        # adv_tier_cap internally; the duplicate call is cheap and
        # keeps the call-site logic uniform.
        sizing_mode = (sizing_cfg.get("sizing_mode") or "equal_slice").lower()
        if sizing_mode == "risk_per_trade":
            stop_pct_q = float((cfg.get("exits") or {}).get("stop_pct") or 0)
            qty = compute_risk_sized_qty(
                entry_price=cand.close,
                stop_pct=stop_pct_q,
                avg_dollar_volume=adv_f,
                cfg=cfg,
            )
        else:
            qty = compute_qty(
                equity=equity,
                close_price=cand.close,
                per_trade_pct=per_trade_pct,
                max_per_trade_dollars=max_per_trade_abs,
                avg_dollar_volume=adv_f,
                max_position_as_adv_frac=effective_adv_frac,
                per_trade_dollars_override=per_trade_dollars_override,
            )
        if qty <= 0:
            _reject("qty_zero", qty=qty)
            continue
        notional = qty * cand.close
        if gross_cap > 0 and (running_gross + notional) > gross_cap:
            _reject("gross_cap", qty=qty)
            continue
        running_gross += notional
        # Per-candidate venue routing. Falls back to the strategy's
        # default_venue_code when the candidate file predates the
        # venue-routing format (pre-Item-2 universe cache).
        venue_code = cand.venue_code or sizing_cfg["default_venue_code"]
        selected.append(Entry(
            ticker=cand.ticker,
            qty=qty,
            close_price=cand.close,
            venue_code=venue_code,
            candidate=cand,
            equity_at_entry=equity,
        ))
    return selected


# ---------------------------------------------------------------- OTOCO


# Bracket-pricing modes. Configured via ``cfg.entry.bracket_pricing_mode``.
#
# * ``"actual_fill"`` (default) — Item 4 fix. Submit the parent MARKET
#   BUY alone, wait for the fill, then submit the OCO take_profit /
#   stop_loss bracket using ``filled_avg_price`` as the reference. This
#   removes the gap-risk regression where a microcap that opens 30%
#   above yesterday's close could ship with a take-profit BELOW the
#   actual fill price (broker-side rejection or instant-target risk).
# * ``"candidate_close"`` — legacy single-shot OTOCO with target / stop
#   priced off the prefilter's prior close. Preserved for backtest
#   parity / debugging.
BRACKET_PRICING_MODES = {"actual_fill", "candidate_close"}


def _bracket_pricing_mode(cfg: dict) -> str:
    mode = (cfg.get("entry") or {}).get("bracket_pricing_mode") or "actual_fill"
    if mode not in BRACKET_PRICING_MODES:
        raise ValueError(
            f"cfg.entry.bracket_pricing_mode must be one of "
            f"{sorted(BRACKET_PRICING_MODES)}; got {mode!r}"
        )
    return mode


# ---------------------------------------------------------------- Item 9 intraday confirmation


def _intraday_confirmation_cfg(cfg: dict) -> dict:
    return ((cfg.get("entry") or {}).get("intraday_confirmation") or {})


def _intraday_window_elapsed(cfg: dict, now_utc: datetime, today_et: date) -> bool:
    """Return True if at least ``window_minutes`` have elapsed since
    today's session start. ``window_minutes <= 0`` always returns True
    (gate disabled)."""
    import pytz  # already a strategy dependency; keep lazy to match the rest of the file

    ic = _intraday_confirmation_cfg(cfg)
    window_min = float(ic.get("window_minutes") or 0)
    if window_min <= 0:
        return True
    session = cfg.get("session") or {}
    start_str = session.get("start") or "09:30"
    tz_name = session.get("timezone") or "America/New_York"
    try:
        h, m = (int(p) for p in start_str.split(":")[:2])
    except Exception:
        h, m = 9, 30
    tz = pytz.timezone(tz_name)
    session_start = tz.localize(datetime.combine(today_et, _dtime(h, m)))
    now_local = now_utc.astimezone(tz)
    return (now_local - session_start) >= timedelta(minutes=window_min)


def _fetch_quote(
    entry: Entry,
    http: httpx.Client,
    api_key: str,
) -> dict[str, Any] | None:
    """POST /api/v2/quotes for a single instrument. Returns the quote
    dict on success or None on any failure — callers treat None as
    "can't confirm, skip the entry"."""
    body = {
        "apikey": api_key,
        "instruments": [{
            "venue_code": entry.venue_code,
            "canonical_symbol": entry.ticker,
        }],
    }
    try:
        r = http.post("/api/v2/quotes", json=body, headers=_api_headers(api_key))
    except httpx.HTTPError as e:
        LOG.warning("intraday quote fetch failed for %s: %s", entry.ticker, e)
        return None
    if r.status_code != 200:
        LOG.warning(
            "intraday quote fetch returned %d for %s: %s",
            r.status_code, entry.ticker, (r.text or "")[:200],
        )
        return None
    try:
        rows = r.json().get("data") or []
    except ValueError:
        return None
    if not rows:
        return None
    return (rows[0] or {}).get("quote") or {}


def _confirm_entry(
    entry: Entry,
    cfg_ic: dict,
    quote: dict[str, Any],
    *,
    now_utc: datetime,
) -> tuple[bool, str | None]:
    """Apply the intraday gates against ``quote``. Returns
    ``(passed, fail_reason)``. fail_reason is None on pass and a
    short label on fail (used in logs and tests)."""
    try:
        bid = float(quote.get("bid") or 0)
        ask = float(quote.get("ask") or 0)
    except (TypeError, ValueError):
        return False, "bad_bid_ask"
    if bid <= 0 or ask <= 0 or ask <= bid:
        return False, "no_quote"
    mid = (bid + ask) / 2.0

    max_spread = float(cfg_ic.get("max_spread_pct") or 0)
    if max_spread > 0 and (ask - bid) / mid > max_spread:
        return False, f"spread>{max_spread:.4f}"

    max_age_s = float(cfg_ic.get("max_quote_age_seconds") or 0)
    if max_age_s > 0:
        ts = quote.get("timestamp")
        if isinstance(ts, str):
            try:
                quote_dt = datetime.fromisoformat(ts.replace("Z", "+00:00"))
                if quote_dt.tzinfo is None:
                    quote_dt = quote_dt.replace(tzinfo=timezone.utc)
                age_s = (now_utc - quote_dt).total_seconds()
                if age_s > max_age_s:
                    return False, f"quote_age>{max_age_s:.0f}s"
            except ValueError:
                # Unparseable timestamp — be conservative and skip.
                return False, "bad_quote_timestamp"

    band = cfg_ic.get("price_band") or {}
    max_above = band.get("max_pct_above_close")
    min_below = band.get("min_pct_below_close")
    if max_above is not None and entry.close_price > 0:
        if mid > entry.close_price * (1.0 + float(max_above)):
            return False, f"chase>{max_above}"
    if min_below is not None and entry.close_price > 0:
        if mid < entry.close_price * (1.0 + float(min_below)):
            return False, f"failure<{min_below}"

    return True, None


# ---------------------------------------------------------------- Phase 4.3 opening range / VWAP


def compute_vwap_from_bars(bars: list[dict]) -> float | None:
    """Volume-weighted average price across ``bars``.

    Each bar is a dict with ``high`` / ``low`` / ``close`` / ``volume``
    keys; typical-price = (high + low + close) / 3. Returns None
    when ``bars`` is empty or total volume is zero (degenerate
    case: no trades in the window).
    """
    if not bars:
        return None
    num = 0.0
    den = 0.0
    for b in bars:
        try:
            h = float(b.get("high"))
            l = float(b.get("low"))
            c = float(b.get("close"))
            v = float(b.get("volume") or 0)
        except (TypeError, ValueError):
            continue
        typ = (h + l + c) / 3.0
        num += typ * v
        den += v
    if den <= 0:
        return None
    return num / den


def build_opening_range_context(
    ticker: str,
    bars_1m: list[dict],
    *,
    prior_opening_vol_mean: float | None = None,
    prior_close: float | None = None,
) -> dict | None:
    """Compute the OR context from a list of 1-minute bars.

    Returns:
      {
        "ticker": ...,
        "high": float, "low": float, "open": float, "close": float,
        "volume": float,
        "vwap": float | None,
        "close_location": float in [0, 1] | None,
        "prior_opening_vol_mean": float | None,
        "opening_rvol": float | None,
        "prior_close": float | None,
      }

    Returns None when ``bars_1m`` is empty (no OR window data
    available — caller should fail-closed). ``close_location`` is
    the OR-bar's close relative to its high/low range — 1.0 means
    closed at the high.
    """
    if not bars_1m:
        return None
    try:
        highs = [float(b["high"]) for b in bars_1m]
        lows = [float(b["low"]) for b in bars_1m]
        opens = [float(b["open"]) for b in bars_1m]
        closes = [float(b["close"]) for b in bars_1m]
        volumes = [float(b.get("volume") or 0) for b in bars_1m]
    except (KeyError, TypeError, ValueError):
        return None

    or_high = max(highs)
    or_low = min(lows)
    or_open = opens[0]
    or_close = closes[-1]
    or_volume = float(sum(volumes))
    rng = or_high - or_low
    close_loc = (
        (or_close - or_low) / rng if rng > 0 else 0.5
    )
    opening_rvol = None
    if prior_opening_vol_mean is not None and prior_opening_vol_mean > 0:
        opening_rvol = or_volume / float(prior_opening_vol_mean)
    return {
        "ticker": ticker,
        "high": or_high,
        "low": or_low,
        "open": or_open,
        "close": or_close,
        "volume": or_volume,
        "vwap": compute_vwap_from_bars(bars_1m),
        "close_location": close_loc,
        "prior_opening_vol_mean": prior_opening_vol_mean,
        "opening_rvol": opening_rvol,
        "prior_close": prior_close,
    }


def confirm_opening_range_vwap(
    entry: "Entry",
    quote: dict[str, Any],
    ctx: dict | None,
    cfg_or: dict,
) -> tuple[bool, str]:
    """Apply the configured OR/VWAP gates against ``ctx`` and the
    live ``quote``.

    Returns ``(passed, reason_label)``. ``reason_label`` is a short
    machine-readable string ("ok" on pass, e.g. "below_vwap" /
    "below_session_open" / "below_prior_close" / "close_location_low"
    / "below_or_high" / "opening_rvol_low" / "no_or_data" on fail).
    """
    if ctx is None:
        return False, "no_or_data"
    try:
        bid = float(quote.get("bid") or 0)
        ask = float(quote.get("ask") or 0)
    except (TypeError, ValueError):
        return False, "bad_quote"
    mid = ((bid + ask) / 2.0) if (bid > 0 and ask > 0 and ask > bid) else None
    if mid is None:
        # Fall back to the OR bar close as a "live price" proxy when
        # the live quote is degenerate — operators see this in
        # paper trading when the quote feed is sparse.
        mid = float(ctx.get("close") or 0)
    if mid <= 0:
        return False, "bad_quote"

    if cfg_or.get("require_price_above_vwap"):
        vwap = ctx.get("vwap")
        if vwap is None or mid < float(vwap):
            return False, "below_vwap"
    if cfg_or.get("require_price_above_session_open"):
        op = ctx.get("open")
        if op is None or mid < float(op):
            return False, "below_session_open"
    if cfg_or.get("require_price_above_prior_close"):
        pc = ctx.get("prior_close")
        if pc is None or mid < float(pc):
            return False, "below_prior_close"
    cl_min = cfg_or.get("require_close_location_min")
    if cl_min is not None:
        cl = ctx.get("close_location")
        if cl is None or float(cl) < float(cl_min):
            return False, "close_location_low"
    mode = (cfg_or.get("breakout_mode") or "above_high").lower()
    or_high = ctx.get("high")
    if or_high is None:
        return False, "no_or_data"
    or_high_f = float(or_high)
    if mode == "above_high":
        if mid < or_high_f:
            return False, "below_or_high"
    elif mode == "above_or_near_high":
        tol = float(cfg_or.get("near_high_tolerance_pct") or 0.0)
        if mid < or_high_f * (1.0 - tol):
            return False, "below_or_high"
    # Volume RVOL check
    vmin = cfg_or.get("opening_volume_rvol_min")
    if vmin is not None:
        ov = ctx.get("opening_rvol")
        if ov is None or float(ov) < float(vmin):
            return False, "opening_rvol_low"
    return True, "ok"


def fetch_or_compute_opening_range_context(
    ticker: str,
    cfg: dict,
    http: httpx.Client | None,
    api_key: str | None,
    *,
    venue_code: str | None,
    avg_volume: float | None,
    avg_dollar_volume: float | None,
    candidate_close: float | None,
    now_utc: datetime,
) -> dict | None:
    """Build the OR context for one ticker.

    Pulls the first ``opening_range.window_minutes`` of today's
    1-minute bars from /api/v2/bars (uses the same auth pattern as
    fetch_daily_bars_for_signal_fade). Returns None on any failure
    — caller treats that as "no OR data; fail-closed".

    Phase 4.4 — prior_opening_vol_mean is approximated as
    ``avg_volume * opening_volume_session_share`` (default 8% of
    daily volume in the first 15 min). Replace with calibrated SIP
    history once available.
    """
    or_cfg = ((cfg.get("entry") or {}).get("intraday_confirmation")
              or {}).get("opening_range") or {}
    window_min = int(or_cfg.get("window_minutes") or 15)
    if http is None or api_key is None:
        return None

    session_cfg = cfg.get("session") or {}
    sizing_cfg = cfg.get("sizing") or {}
    venue = venue_code or sizing_cfg.get("default_venue_code") or "XNAS"

    import pytz
    tz = pytz.timezone(session_cfg.get("timezone") or "America/New_York")
    today_et = _to_eastern(now_utc).date()
    try:
        sh, sm = (int(p) for p in str(session_cfg.get("start") or "09:30").split(":")[:2])
    except Exception:
        sh, sm = 9, 30
    session_start = tz.localize(datetime.combine(today_et, _dtime(sh, sm)))
    or_end = session_start + timedelta(minutes=window_min)
    body = {
        "apikey": api_key,
        "instrument": {"venue_code": venue, "canonical_symbol": ticker},
        "interval": "1m",
        "start": session_start.astimezone(timezone.utc).isoformat(),
        "end": or_end.astimezone(timezone.utc).isoformat(),
    }
    try:
        r = http.post("/api/v2/bars", json=body, headers=_api_headers(api_key))
    except Exception as e:
        LOG.warning("opening_range bars fetch failed for %s: %s", ticker, e)
        return None
    if r.status_code != 200:
        LOG.warning(
            "opening_range bars HTTP %d for %s: %s",
            r.status_code, ticker, (r.text or "")[:200],
        )
        return None
    try:
        payload = r.json().get("data") or {}
    except ValueError:
        return None
    rows = payload.get("bars") or []
    if not rows:
        return None

    # Approximate prior_opening_vol_mean. avg_volume is the rolling
    # daily-volume mean from the prefilter; multiply by the
    # configured first-X-minutes share.
    session_share = float(or_cfg.get("opening_volume_session_share") or 0.08)
    prior_opening_vol_mean = (
        float(avg_volume) * session_share
        if avg_volume is not None and avg_volume > 0
        else None
    )
    return build_opening_range_context(
        ticker, rows,
        prior_opening_vol_mean=prior_opening_vol_mean,
        prior_close=candidate_close,
    )


def _reason_label_for_confirmation_fail(raw: str | None) -> str:
    """Map :func:`_confirm_entry`'s human-readable reason into the
    canonical Phase 1.4 reason label set.

    The raw strings carry inline thresholds (e.g. ``"spread>0.0200"``)
    for log readability — they're not stable for analytics. The
    canonical labels are stable.
    """
    if not raw:
        return "bad_quote"
    if raw == "no_quote":
        return "no_quote"
    if raw == "bad_bid_ask" or raw == "bad_quote_timestamp":
        return "bad_quote"
    if raw.startswith("spread"):
        return "spread_too_wide"
    if raw.startswith("quote_age"):
        return "quote_stale"
    if raw.startswith("chase"):
        return "chase"
    if raw.startswith("failure"):
        return "failure_band"
    return "bad_quote"


def _confirmation_streak(state: State | None) -> dict[str, int]:
    """Phase 4.2 — transient per-ticker stable-quote streak counter.

    Stored under ``state["confirmation_streak"]`` so it survives
    across ticks within a session. reset_for_new_session does NOT
    explicitly clear it (it's name-scoped, not date-scoped), but a
    new session means a fresh slate so the dict stays effectively
    empty until the first new candidate arrives.
    """
    if state is None:
        # Test/legacy path with no state — return a throwaway dict
        # that the caller will not persist.
        return {}
    return state.setdefault("confirmation_streak", {})


def filter_by_intraday_confirmation(
    entries: list[Entry],
    cfg: dict,
    http: httpx.Client,
    api_key: str,
    *,
    now_utc: datetime | None = None,
    band_override: dict | None = None,
    state: State | None = None,
    entry_trigger: str = "session_open",
) -> list[Entry]:
    """Item 9: gate each entry on a fresh quote. Skips a name when
    spread is too wide, the quote is stale, or the live price is
    outside the configured band relative to candidate.close. Returns
    the filtered list. When the gate is disabled (``enabled: false``
    or empty config) returns the input unchanged.

    ``band_override``: when set, replaces ``price_band`` in the gate
    config for this call only. Post-closure rescreens pass the tighter
    ``post_closure_price_band`` so they don't chase names that have
    already run since the open.

    Fail-closed: a quote that returns None, has an unparseable
    timestamp, or has bad bid/ask values causes the candidate to be
    rejected (not silently passed). Operators relying on this gate
    need it to err on the side of skipping the trade.

    Phase 1.4: every rejection emits a universal ``entry_decision``
    event keyed to the canonical reason label set
    (:data:`ENTRY_DECISION_REASONS`).
    """
    ic = _intraday_confirmation_cfg(cfg)
    if not ic.get("enabled"):
        return entries
    if band_override is not None:
        # Shallow-copy and substitute price_band so the original cfg
        # dict is not mutated for the next caller.
        ic = dict(ic)
        ic["price_band"] = band_override
    now_utc = now_utc or datetime.now(timezone.utc)
    # Phase 4.2 — stable-quote streak threshold. Default 1 = legacy
    # single-tick behavior.
    required_streak = int(ic.get("require_stable_quote_checks") or 1)
    streaks = _confirmation_streak(state)
    # Phase 4.3 — opening-range / VWAP context (per-ticker cached
    # within this call so multiple entries on the same ticker reuse).
    or_cfg = (ic.get("opening_range") or {})
    or_enabled = bool(or_cfg.get("enabled"))
    or_ctx_cache: dict[str, dict | None] = {}
    out: list[Entry] = []
    for rank, entry in enumerate(entries, start=1):
        quote = _fetch_quote(entry, http, api_key)
        if quote is None:
            LOG.info(
                "intraday_confirmation: %s — no quote available, skipping",
                entry.ticker,
            )
            # Reset the streak on quote miss so a momentarily
            # unavailable quote does not "freeze" prior pass count.
            streaks.pop(entry.ticker, None)
            if state is not None:
                emit_entry_decision_rejected(
                    cfg, candidate=entry.candidate, state=state,
                    reason="no_quote",
                    entry_trigger=entry_trigger,
                    candidate_rank=rank,
                    qty=entry.qty, venue_code=entry.venue_code,
                )
            continue
        passed, raw_reason = _confirm_entry(entry, ic, quote, now_utc=now_utc)
        if not passed:
            # Reset streak on fail.
            streaks.pop(entry.ticker, None)
            LOG.info(
                "intraday_confirmation: %s rejected (%s) bid=%s ask=%s",
                entry.ticker, raw_reason,
                quote.get("bid"), quote.get("ask"),
            )
            if state is not None:
                emit_entry_decision_rejected(
                    cfg, candidate=entry.candidate, state=state,
                    reason=_reason_label_for_confirmation_fail(raw_reason),
                    entry_trigger=entry_trigger,
                    candidate_rank=rank,
                    qty=entry.qty, venue_code=entry.venue_code,
                    quote=quote,
                )
            continue

        # Phase 4.3 — OR/VWAP gate (only when enabled). The check
        # runs AFTER the spread/age/band gates because OR data
        # requires more fetching; cheap checks reject first.
        if or_enabled:
            ctx = or_ctx_cache.get(entry.ticker)
            if ctx is None:
                ctx = fetch_or_compute_opening_range_context(
                    entry.ticker, cfg, http, api_key,
                    venue_code=entry.venue_code,
                    avg_volume=(
                        (entry.candidate.features or {}).get("avg_volume")
                        if entry.candidate else None
                    ),
                    avg_dollar_volume=(
                        (entry.candidate.features or {}).get("avg_dollar_volume")
                        if entry.candidate else None
                    ),
                    candidate_close=entry.close_price,
                    now_utc=now_utc,
                )
                or_ctx_cache[entry.ticker] = ctx
            or_pass, or_reason = confirm_opening_range_vwap(
                entry, quote, ctx, or_cfg,
            )
            if not or_pass:
                streaks.pop(entry.ticker, None)
                LOG.info(
                    "opening_range_confirmation: %s rejected (%s)",
                    entry.ticker, or_reason,
                )
                if state is not None:
                    emit_entry_decision_rejected(
                        cfg, candidate=entry.candidate, state=state,
                        reason="opening_range_failed",
                        entry_trigger=entry_trigger,
                        candidate_rank=rank,
                        qty=entry.qty, venue_code=entry.venue_code,
                        quote=quote,
                    )
                continue

        # Pass — bump streak. Admit only when threshold reached.
        new_count = int(streaks.get(entry.ticker, 0)) + 1
        streaks[entry.ticker] = new_count
        if new_count >= required_streak:
            # Reset after admit so subsequent passes start fresh
            # (defensive — admitted entries are popped from the
            # candidate slate by the caller, but a re-entry in a
            # later session shouldn't inherit stale streak count).
            streaks.pop(entry.ticker, None)
            out.append(entry)
        else:
            LOG.info(
                "intraday_confirmation: %s streak=%d/%d — defer to next tick",
                entry.ticker, new_count, required_streak,
            )
            # Pre-threshold pass: drop from this slate; the
            # next-tick pass will retry and bump the streak. No
            # entry_decision event yet — neither accepted nor
            # rejected per the audit's "exactly one event"
            # contract.
    return out


def submit_entry(
    entry: Entry,
    cfg: dict,
    http: httpx.Client,
    api_key: str,
    *,
    state: State,
    state_path: Path,
    link_id_override: str | None = None,
    entry_trigger: str = "session_open",
) -> dict[str, Any]:
    """Dispatch to the configured bracket-pricing mode. The legacy
    ``submit_otoco`` is kept as the ``candidate_close`` implementation
    (Phase 2 contract). ``actual_fill`` uses ``submit_parent_market_buy``
    and defers child submission to ``submit_pending_oco_children``
    after the parent fill arrives in poll_fills.

    ``link_id_override`` is plumbed in by ``run_session_entry_pass``
    so the entry_decision record (written before this call) shares the
    link_id with the submitted order — that's the join key for per-
    trade jsonl files.

    ``entry_trigger`` is recorded on the position record so the
    opened / closure jsonl entries carry it through to analytics.
    """
    mode = _bracket_pricing_mode(cfg)
    if mode == "actual_fill":
        # Phase 6.3 — dispatch on cfg.entry.order_style.
        order_style = (
            (cfg.get("entry") or {}).get("order_style") or "market"
        ).lower()
        if order_style == "marketable_limit":
            quote = _fetch_quote(entry, http, api_key)
            if quote is None:
                LOG.warning(
                    "marketable_limit: no quote for %s — skipping",
                    entry.ticker,
                )
                emit_entry_decision_rejected(
                    cfg, candidate=entry.candidate, state=state,
                    reason="marketable_limit_no_quote",
                    entry_trigger=entry_trigger,
                    candidate_rank=None,
                    qty=entry.qty, venue_code=entry.venue_code,
                )
                return {"error": {"code": "no_quote"}, "status": 0}
            limit_price = compute_marketable_buy_limit(entry, quote, cfg)
            if limit_price is None:
                emit_entry_decision_rejected(
                    cfg, candidate=entry.candidate, state=state,
                    reason="marketable_limit_no_quote",
                    entry_trigger=entry_trigger,
                    candidate_rank=None,
                    qty=entry.qty, venue_code=entry.venue_code,
                    quote=quote,
                )
                return {"error": {"code": "bad_quote"}, "status": 0}
            return submit_parent_marketable_limit_buy(
                entry, limit_price, cfg, http, api_key,
                state=state, state_path=state_path,
                link_id_override=link_id_override,
                entry_trigger=entry_trigger,
            )
        return submit_parent_market_buy(
            entry, cfg, http, api_key,
            state=state, state_path=state_path,
            link_id_override=link_id_override,
            entry_trigger=entry_trigger,
        )
    return submit_otoco(
        entry, cfg, http, api_key,
        state=state, state_path=state_path,
        link_id_override=link_id_override,
        entry_trigger=entry_trigger,
    )


def submit_parent_market_buy(
    entry: Entry,
    cfg: dict,
    http: httpx.Client,
    api_key: str,
    *,
    state: State,
    state_path: Path,
    link_id_override: str | None = None,
    entry_trigger: str = "session_open",
) -> dict[str, Any]:
    """Item 4 (actual_fill mode): submit a stand-alone parent MARKET
    BUY via /api/v2/orders. The OCO take_profit / stop_loss children
    are submitted later by :func:`submit_pending_oco_children` once
    the parent's filled_avg_price is known.

    Records the same state shape as :func:`submit_otoco` but with empty
    child_order_ids and ``bracket_pricing_mode="actual_fill"`` plus
    cached ``target_pct`` / ``stop_pct`` so the post-fill submitter can
    derive the bracket levels without a second cfg dependency."""
    venue_code = entry.venue_code or cfg["sizing"]["default_venue_code"]
    link_id = link_id_override or f"BOWAKA-{entry.ticker}-{int(time.time())}"

    body = {
        "apikey": api_key,
        "instrument": {
            "venue_code": venue_code,
            "canonical_symbol": entry.ticker,
        },
        "side": "BUY",
        "order_type": "MARKET",
        "quantity": str(entry.qty),
        "quantity_unit": "WHOLE",
        "time_in_force": "DAY",
        "session": "REGULAR",
    }
    r = http.post("/api/v2/orders", json=body, headers=_api_headers(api_key))
    parsed = r.json() if r.content else {}

    if r.status_code == 200:
        data = parsed.get("data", {})
        native = data.get("native_response") or {}
        parent_id = (
            native.get("id")
            or native.get("order_id")
            or data.get("order_id")
            or ""
        )
        state.setdefault("open_positions", {})[entry.ticker] = {
            "parent_order_id": parent_id,
            "child_order_ids": {"target": "", "stop": ""},
            "qty": entry.qty,
            "entry_price": None,
            "entry_timestamp": datetime.now(timezone.utc).isoformat(),
            "entry_features": entry.candidate.features,
            "status": "pending_fill",
            "link_id": link_id,
            "venue_code": venue_code,
            "exchange": entry.candidate.exchange,
            "bracket_pricing_mode": "actual_fill",
            "target_pct": float(cfg["exits"]["target_pct"]),
            "stop_pct": float(cfg["exits"]["stop_pct"]),
            "candidate_close": entry.close_price,
            "signal_strength": entry.candidate.signal_strength,
            "equity_at_entry": entry.equity_at_entry,
            "entry_trigger": entry_trigger,
            # Tracks worst/best fill-relative excursion across the
            # position's life. Initialized to entry_price on parent
            # fill; updated by write_daily_marks each session end.
            "peak_since_entry": None,
            "trough_since_entry": None,
            # Phase 5.2 — protected-position invariant fields. Set
            # when the parent fills (poll_fills); the protection
            # enforcer reads them on every tick after the fill.
            "parent_filled_at": None,
            "protection_status": "none",
            "protection_deadline_at": None,
            "oco_attach_attempts": 0,
            "fallback_stop_order_id": None,
            "protection_violation": False,
            # Phase 6.5 — planned-risk dollars (closure R-multiple).
            "planned_risk_dollars": _planned_risk_for_entry(entry, cfg),
            # Phase 6.3 metadata so analytics can split market vs
            # marketable_limit fills.
            "entry_order_style": "market",
        }
        save_state(state, state_path)
        LOG.info("Parent MARKET BUY submitted (actual_fill mode): %s qty=%d parent=%s",
                 entry.ticker, entry.qty, parent_id)
        emit_parent_submitted(
            cfg, link_id=link_id, ticker=entry.ticker,
            parent_id=parent_id, qty=entry.qty, venue_code=venue_code,
            http_status=r.status_code,
        )
        return parsed

    err = (parsed.get("error") or {}) if isinstance(parsed, dict) else {}
    code = (err.get("code") or "").lower()
    msg = err.get("message") or ""

    if r.status_code == 422 and (
        "instrument" in code
        or "broker_map" in msg.lower()
        or "not mapped" in msg.lower()
    ):
        LOG.error("Instrument not mapped for %s: %s", entry.ticker, err)
        state.setdefault("halt_skip_today", []).append(entry.ticker)
        save_state(state, state_path)
        return {"error": err, "status": r.status_code}

    if r.status_code == 503:
        LOG.error(
            "Promoted lane unavailable (%s); operator action required: %s",
            code, err,
        )
        return {"error": err, "status": r.status_code}

    LOG.error("Parent MARKET BUY failed for %s: HTTP %d %s",
              entry.ticker, r.status_code, parsed)
    return {"error": err, "status": r.status_code}


# ---------------------------------------------------------------- Phase 6.3 — marketable-limit entry


def max_entry_slippage_for_candidate(entry: "Entry", cfg: dict) -> float:
    """Return the slippage cap for ``entry``. Tiered (per ADV) when
    ``cfg.entry.max_entry_slippage_by_adv_tier`` is set; falls back
    to the flat ``cfg.entry.max_entry_slippage_pct``."""
    entry_cfg = cfg.get("entry") or {}
    tiers = entry_cfg.get("max_entry_slippage_by_adv_tier") or []
    adv = None
    if entry.candidate and entry.candidate.features:
        adv = entry.candidate.features.get("avg_dollar_volume")
    if tiers and adv is not None:
        def _key(t: dict) -> float:
            v = t.get("max_adv_dollars")
            return float(v) if v is not None else float("inf")
        for t in sorted(tiers, key=_key):
            bound = t.get("max_adv_dollars")
            bound_f = float(bound) if bound is not None else float("inf")
            if float(adv) <= bound_f:
                return float(t.get("max_slippage_pct") or 0.0)
    return float(entry_cfg.get("max_entry_slippage_pct") or 0.0)


def compute_marketable_buy_limit(
    entry: "Entry", quote: dict[str, Any], cfg: dict,
) -> float | None:
    """Phase 6.3 — limit price = min(ask*(1+slip), close*(1+max_above)).

    Returns None when the ask is missing/zero (caller skips the
    entry with reason="marketable_limit_no_quote"). The price-band
    cap prevents chase prices above the operator's chase ceiling.
    """
    try:
        ask = float(quote.get("ask") or 0)
    except (TypeError, ValueError):
        return None
    if ask <= 0:
        return None
    slip = max_entry_slippage_for_candidate(entry, cfg)
    raw_limit = ask * (1.0 + slip)
    band = (((cfg.get("entry") or {}).get("intraday_confirmation") or {})
            .get("price_band") or {})
    max_above = band.get("max_pct_above_close")
    if max_above is not None and entry.close_price > 0:
        chase_cap = entry.close_price * (1.0 + float(max_above))
        raw_limit = min(raw_limit, chase_cap)
    return round(raw_limit, 2)


def submit_parent_marketable_limit_buy(
    entry: "Entry",
    limit_price: float,
    cfg: dict,
    http: httpx.Client,
    api_key: str,
    *,
    state: State,
    state_path: Path,
    link_id_override: str | None = None,
    entry_trigger: str = "session_open",
) -> dict[str, Any]:
    """Phase 6.3 parent submission: LIMIT BUY (DAY TIF) at
    ``limit_price``. Position state records ``entry_order_style`` and
    ``entry_limit_price`` so poll_fills can detect timeout and
    cancel-free-the-slot when the fill never comes.

    On non-200 the position is NOT stored; the caller re-tries on
    the next tick (or moves on, depending on broker error code).
    """
    venue_code = entry.venue_code or cfg["sizing"]["default_venue_code"]
    link_id = link_id_override or f"BOWAKA-{entry.ticker}-{int(time.time())}"
    body = {
        "apikey": api_key,
        "instrument": {"venue_code": venue_code,
                       "canonical_symbol": entry.ticker},
        "side": "BUY",
        "order_type": "LIMIT",
        "price": str(limit_price),
        "quantity": str(entry.qty),
        "quantity_unit": "WHOLE",
        "time_in_force": "DAY",
        "session": "REGULAR",
    }
    r = http.post("/api/v2/orders", json=body, headers=_api_headers(api_key))
    parsed = r.json() if r.content else {}

    if r.status_code == 200:
        data = parsed.get("data", {})
        native = data.get("native_response") or {}
        parent_id = (
            native.get("id") or native.get("order_id")
            or data.get("order_id") or ""
        )
        state.setdefault("open_positions", {})[entry.ticker] = {
            "parent_order_id": parent_id,
            "child_order_ids": {"target": "", "stop": ""},
            "qty": entry.qty,
            "entry_price": None,
            "entry_timestamp": datetime.now(timezone.utc).isoformat(),
            "entry_features": entry.candidate.features,
            "status": "pending_fill",
            "link_id": link_id,
            "venue_code": venue_code,
            "exchange": entry.candidate.exchange,
            "bracket_pricing_mode": "actual_fill",
            "target_pct": float(cfg["exits"]["target_pct"]),
            "stop_pct": float(cfg["exits"]["stop_pct"]),
            "candidate_close": entry.close_price,
            "signal_strength": entry.candidate.signal_strength,
            "equity_at_entry": entry.equity_at_entry,
            "entry_trigger": entry_trigger,
            "peak_since_entry": None,
            "trough_since_entry": None,
            # Phase 5.2 protection fields (mirror submit_parent_market_buy).
            "parent_filled_at": None,
            "protection_status": "none",
            "protection_deadline_at": None,
            "oco_attach_attempts": 0,
            "fallback_stop_order_id": None,
            "protection_violation": False,
            # Phase 6.3 marketable-limit metadata.
            "entry_order_style": "marketable_limit",
            "entry_limit_price": float(limit_price),
            # Phase 6.5 planned-risk for R-multiple.
            "planned_risk_dollars": _planned_risk_for_entry(entry, cfg),
        }
        save_state(state, state_path)
        LOG.info(
            "Parent LIMIT BUY (marketable_limit) submitted: %s qty=%d "
            "limit=%.4f parent=%s",
            entry.ticker, entry.qty, limit_price, parent_id,
        )
        emit_parent_submitted(
            cfg, link_id=link_id, ticker=entry.ticker,
            parent_id=parent_id, qty=entry.qty, venue_code=venue_code,
            http_status=r.status_code,
        )
        return parsed

    err = (parsed.get("error") or {}) if isinstance(parsed, dict) else {}
    if r.status_code == 422:
        state.setdefault("halt_skip_today", []).append(entry.ticker)
        save_state(state, state_path)
    LOG.error(
        "Parent LIMIT BUY (marketable_limit) failed for %s: HTTP %d %s",
        entry.ticker, r.status_code, parsed,
    )
    return {"error": err, "status": r.status_code}


def _planned_risk_for_entry(entry: "Entry", cfg: dict) -> float | None:
    """Planned dollar risk for the order — Phase 6.5 plumbs this into
    ledger closures for proper R-multiple computation."""
    sizing = cfg.get("sizing") or {}
    mode = (sizing.get("sizing_mode") or "equal_slice").lower()
    if mode == "risk_per_trade":
        return float(sizing.get("target_risk_dollars") or 0) or None
    # equal_slice mode uses stop_pct-derived planned risk.
    stop_pct = float((cfg.get("exits") or {}).get("stop_pct") or 0)
    if stop_pct <= 0 or entry.qty <= 0 or entry.close_price <= 0:
        return None
    return float(entry.close_price) * stop_pct * float(entry.qty)


def submit_oco_children(
    ticker: str,
    pos: dict[str, Any],
    cfg: dict,
    http: httpx.Client,
    api_key: str,
    *,
    state: State,
    state_path: Path,
) -> dict[str, Any] | None:
    """Submit an OCO take_profit / stop_loss bracket against an
    already-filled parent position. Used by the actual_fill bracket
    mode after :func:`poll_fills` records the parent's fill price.

    Idempotent — if ``pos["child_order_ids"]["target"]`` already has a
    value the call short-circuits with ``None``. On submission failure
    the position is left in ``status="filled"`` with empty child IDs;
    the next tick will retry.
    """
    children = pos.get("child_order_ids") or {}
    if children.get("target") and children.get("stop"):
        return None

    fill_price = pos.get("entry_price")
    qty = int(pos.get("qty") or 0)
    venue_code = pos.get("venue_code") or cfg["sizing"]["default_venue_code"]
    target_pct = float(pos.get("target_pct") or cfg["exits"]["target_pct"])
    stop_pct = float(pos.get("stop_pct") or cfg["exits"]["stop_pct"])

    if fill_price is None or fill_price <= 0:
        LOG.warning(
            "submit_oco_children: %s has no fill_price yet; skipping",
            ticker,
        )
        return None
    if qty <= 0:
        LOG.warning(
            "submit_oco_children: %s has qty=%d; skipping",
            ticker, qty,
        )
        return None

    target_price = round(float(fill_price) * (1.0 + target_pct), 2)
    stop_price = round(float(fill_price) * (1.0 - stop_pct), 2)
    # Each OCO submission needs a unique client_order_id. The
    # position's link_id is fixed for the trade's lifetime; appending
    # the current unix timestamp keeps every retry / re-bracket
    # attempt distinct from prior submissions Alpaca remembers
    # (40010001 "client_order_id must be unique" otherwise rejects
    # the next-day re-bracket after the original OCO expired).
    link_id = (
        f"{pos.get('link_id') or 'BOWAKA-' + ticker}-OCO-{int(time.time())}"
    )

    # Overnight gap protection: default to GTC so the bracket survives
    # past 16:00 ET expiry and stays live for next-day open. DAY-TIF
    # OCOs auto-cancel at session close, leaving positions naked
    # overnight — observed live (BLDP, 2026-05-08) costing ~$300+ in
    # slippage when the next-day reactive re-bracket arrived after the
    # price had already drifted past the stop level. Operator can
    # opt back to DAY via ``cfg.exits.oco_time_in_force`` for
    # backtest-parity / debugging.
    oco_tif = (cfg.get("exits") or {}).get("oco_time_in_force", "GTC")

    body = {
        "apikey": api_key,
        "combo_type": "OCO",
        "time_in_force": oco_tif,
        "session": "REGULAR",
        "link_id": link_id,
        "legs": [
            {
                "instrument_ref": {
                    "venue_code": venue_code,
                    "canonical_symbol": ticker,
                },
                "side": "SELL",
                "quantity": str(qty),
                "quantity_unit": "WHOLE",
                "order_type": "LIMIT",
                "price": str(target_price),
            },
            {
                "instrument_ref": {
                    "venue_code": venue_code,
                    "canonical_symbol": ticker,
                },
                "side": "SELL",
                "quantity": str(qty),
                "quantity_unit": "WHOLE",
                "order_type": "STOP",
                "trigger_price": str(stop_price),
            },
        ],
    }
    r = http.post("/api/v2/orders/combo",
                  json=body,
                  headers=_api_headers(api_key))
    parsed = r.json() if r.content else {}

    if r.status_code != 200:
        err = (parsed.get("error") or {}) if isinstance(parsed, dict) else {}
        LOG.error(
            "OCO bracket submission failed for %s (fill=%.4f): HTTP %d %s",
            ticker, float(fill_price), r.status_code, err,
        )
        return {"error": err, "status": r.status_code}

    data = parsed.get("data") or {}
    native = data.get("native_response") or {}
    child_orders = native.get("legs") or []
    parent_response_id = native.get("id") or native.get("order_id") or ""

    # Alpaca's OCO response shape: ``id`` is the SELL LIMIT (the
    # take-profit) and ``legs[0]`` is the SELL STOP. There's no
    # separate "main" parent — the limit order plays both roles.
    # First pass: scan legs for whichever side we can identify by
    # order_type. Second pass: if target is still empty after the
    # scan, use the response's top-level id (the limit) as target.
    # Same fallback for stop, in case the legs come back empty.
    target_id = ""
    stop_id = ""
    for leg in child_orders:
        otype = (leg.get("order_type") or leg.get("type") or "").lower()
        if "limit" in otype and not target_id:
            target_id = leg.get("id") or leg.get("order_id") or ""
        elif "stop" in otype and not stop_id:
            stop_id = leg.get("id") or leg.get("order_id") or ""
    # OCO-specific: if no LIMIT leg was seen, the parent response IS
    # the take-profit. Fall back to it before resorting to leg[0].
    if not target_id and parent_response_id:
        target_id = parent_response_id
    if not stop_id and len(child_orders) >= 1:
        # Last-resort fallback (legs[0] should already have been seen
        # as 'stop' in the first pass for OCO). Only triggers when the
        # broker surfaces leg types in a way the loop above missed.
        stop_id = child_orders[0].get("id") or ""

    pos["child_order_ids"] = {"target": target_id, "stop": stop_id}
    pos["target_price"] = target_price
    pos["stop_price"] = stop_price
    # Item-(post-rebracket): clear any prior reconcile flag so the
    # next reconcile run doesn't re-flag these IDs as stale.
    pos.pop("child_status_at_recon", None)
    save_state(state, state_path)
    LOG.info(
        "OCO bracket attached: %s fill=%.4f target=%.2f(id=%s) stop=%.2f(id=%s)",
        ticker, float(fill_price), target_price, target_id, stop_price, stop_id,
    )
    emit_bracket_attached(
        cfg, pos=pos,
        target_id=target_id, stop_id=stop_id,
        target_price=target_price, stop_price=stop_price,
    )
    return parsed


def submit_pending_oco_children(
    state: State,
    cfg: dict,
    http: httpx.Client,
    api_key: str,
    *,
    state_path: Path,
) -> list[str]:
    """Idempotent post-fill bracket sweep. Walks open positions whose
    bracket_pricing_mode is "actual_fill", whose status is "filled",
    and whose child_order_ids are still empty — and submits an OCO
    take_profit / stop_loss bracket priced off the recorded
    entry_price. Called once per main-loop tick after poll_fills.

    Returns the tickers that received a fresh OCO bracket this call.
    """
    out: list[str] = []
    open_positions = state.get("open_positions") or {}
    for ticker, pos in list(open_positions.items()):
        if pos.get("bracket_pricing_mode") != "actual_fill":
            continue
        if pos.get("status") != "filled":
            continue
        children = pos.get("child_order_ids") or {}
        if children.get("target") and children.get("stop"):
            continue
        try:
            res = submit_oco_children(
                ticker, pos, cfg, http, api_key,
                state=state, state_path=state_path,
            )
        except httpx.HTTPError as e:
            LOG.exception("submit_oco_children network error for %s: %s", ticker, e)
            continue
        if res and "error" not in res:
            out.append(ticker)
    return out


def submit_otoco(
    entry: Entry,
    cfg: dict,
    http: httpx.Client,
    api_key: str,
    *,
    state: State,
    state_path: Path,
    link_id_override: str | None = None,
    entry_trigger: str = "session_open",
) -> dict[str, Any]:
    """Legacy ``candidate_close`` mode: POST /api/v2/orders/combo with
    an OTOCO bracket priced off the prefilter's prior close. Records
    state on success. Marks halt_skip_today on bracket / instrument-
    mapping 422s. Surfaces 503 translator/lane errors loudly.

    Kept for backtest parity / debugging. Production runs default to
    the ``actual_fill`` mode (see :func:`submit_entry`).
    """
    target = round(entry.close_price * (1.0 + float(cfg["exits"]["target_pct"])), 2)
    stop = round(entry.close_price * (1.0 - float(cfg["exits"]["stop_pct"])), 2)
    # Item 2: route per-candidate. The prefilter's universe spans
    # NASDAQ/NYSE/AMEX/ARCA/BATS, and a hardcoded XNAS used to make
    # /api/v2 instrument resolution fail for every non-NASDAQ ticker.
    venue_code = entry.venue_code or cfg["sizing"]["default_venue_code"]
    link_id = link_id_override or f"BOWAKA-{entry.ticker}-{int(time.time())}"

    body = {
        "apikey": api_key,
        "combo_type": "OTOCO",
        "time_in_force": "DAY",
        "session": "REGULAR",
        "link_id": link_id,
        "legs": [
            {
                "instrument_ref": {
                    "venue_code": venue_code,
                    "canonical_symbol": entry.ticker,
                },
                "side": "BUY",
                "quantity": str(entry.qty),
                "quantity_unit": "WHOLE",
                "order_type": "MARKET",
            },
            {
                "instrument_ref": {
                    "venue_code": venue_code,
                    "canonical_symbol": entry.ticker,
                },
                "side": "SELL",
                "quantity": str(entry.qty),
                "quantity_unit": "WHOLE",
                "order_type": "LIMIT",
                "price": str(target),
            },
            {
                "instrument_ref": {
                    "venue_code": venue_code,
                    "canonical_symbol": entry.ticker,
                },
                "side": "SELL",
                "quantity": str(entry.qty),
                "quantity_unit": "WHOLE",
                "order_type": "STOP",
                "trigger_price": str(stop),
            },
        ],
    }
    r = http.post("/api/v2/orders/combo",
                  json=body,
                  headers=_api_headers(api_key))
    parsed = r.json() if r.content else {}

    if r.status_code == 200:
        data = parsed.get("data", {})
        native = data.get("native_response") or {}
        # Alpaca's bracket native response: parent has ``id``; child
        # orders sit under ``legs`` (alpaca naming).
        parent_id = native.get("id") or native.get("order_id") or ""
        children = native.get("legs") or []
        target_id = ""
        stop_id = ""
        for leg in children:
            otype = (leg.get("order_type") or leg.get("type") or "").lower()
            if "limit" in otype and not target_id:
                target_id = leg.get("id") or leg.get("order_id") or ""
            elif "stop" in otype and not stop_id:
                stop_id = leg.get("id") or leg.get("order_id") or ""
        # Fallback for translators that surface the children differently.
        if not target_id and len(children) >= 1:
            target_id = children[0].get("id") or ""
        if not stop_id and len(children) >= 2:
            stop_id = children[1].get("id") or ""

        state.setdefault("open_positions", {})[entry.ticker] = {
            "parent_order_id": parent_id,
            "child_order_ids": {"target": target_id, "stop": stop_id},
            "qty": entry.qty,
            "entry_price": None,
            "entry_timestamp": datetime.now(timezone.utc).isoformat(),
            "entry_features": entry.candidate.features,
            "status": "pending_fill",
            "link_id": link_id,
            "venue_code": venue_code,
            "exchange": entry.candidate.exchange,
            "target_price": target,
            "stop_price": stop,
            # Same analytic-logging fields as submit_parent_market_buy
            # so the candidate_close mode produces comparable opened
            # records.
            "bracket_pricing_mode": "candidate_close",
            "target_pct": float(cfg["exits"]["target_pct"]),
            "stop_pct": float(cfg["exits"]["stop_pct"]),
            "candidate_close": entry.close_price,
            "signal_strength": entry.candidate.signal_strength,
            "equity_at_entry": entry.equity_at_entry,
            "entry_trigger": entry_trigger,
            "peak_since_entry": None,
            "trough_since_entry": None,
        }
        save_state(state, state_path)
        LOG.info("OTOCO submitted: %s qty=%d parent=%s",
                 entry.ticker, entry.qty, parent_id)
        emit_parent_submitted(
            cfg, link_id=link_id, ticker=entry.ticker,
            parent_id=parent_id, qty=entry.qty, venue_code=venue_code,
            http_status=r.status_code,
        )
        # In legacy candidate_close mode the bracket children come
        # back atomically with the parent, so we record the
        # bracket-attached event right here using the IDs already
        # parsed above.
        emit_bracket_attached(
            cfg, pos=state["open_positions"][entry.ticker],
            target_id=target_id, stop_id=stop_id,
            target_price=target, stop_price=stop,
        )
        return parsed

    err = (parsed.get("error") or {}) if isinstance(parsed, dict) else {}
    code = (err.get("code") or "").lower()
    msg = err.get("message") or ""

    if r.status_code == 422 and (
        code == "unsupported_capability"
        and "bracket" in str(err.get("details", {})).lower()
    ):
        LOG.error("OTOCO bracket capability rejected for %s: %s", entry.ticker, err)
        state.setdefault("halt_skip_today", []).append(entry.ticker)
        save_state(state, state_path)
        return {"error": err, "status": r.status_code}

    if r.status_code == 422 and (
        "instrument" in code
        or "instrument_not_resolvable" in code
        or "broker_map" in msg.lower()
        or "not mapped" in msg.lower()
    ):
        LOG.error("Instrument not mapped for %s: %s", entry.ticker, err)
        state.setdefault("halt_skip_today", []).append(entry.ticker)
        save_state(state, state_path)
        return {"error": err, "status": r.status_code}

    if r.status_code == 503:
        LOG.error(
            "Promoted lane unavailable (%s); operator action required: %s",
            code, err,
        )
        return {"error": err, "status": r.status_code}

    # Anything else — log and skip the ticker for safety; do NOT add to
    # halt list (might be a transient broker error worth retrying next session).
    LOG.error("OTOCO submission failed for %s (HTTP %d): %s",
              entry.ticker, r.status_code, parsed)
    return {"error": err or {"code": "unknown"}, "status": r.status_code}


# ---------------------------------------------------------------- single market


# Phase 4.1 — explicit allow-list of (order_type, time_in_force)
# combinations. The 2026-05-15 incident was an OPG-rejected MARKET
# SELL: the broker rejects MARKET+OPG because OPG is reserved for
# auction orders (limit_on_open / market_on_open).
VALID_EXIT_COMBINATIONS: frozenset[tuple[str, str]] = frozenset({
    ("market", "DAY"),
    ("market", "GTC"),
    ("limit", "DAY"),
    ("limit", "GTC"),
    ("market_on_close", "CLS"),
    ("limit_on_close", "CLS"),
    ("market_on_open", "OPG"),
    ("limit_on_open", "OPG"),
})


def _validate_exit_combination(order_type: str, time_in_force: str) -> None:
    """Raises ValueError on an invalid pair. Called from every exit
    submit helper before any HTTP I/O — fail fast."""
    key = (order_type.lower(), time_in_force.upper())
    if key not in VALID_EXIT_COMBINATIONS:
        raise ValueError(
            f"invalid order_type/time_in_force combination: "
            f"order_type={order_type!r} time_in_force={time_in_force!r}. "
            f"Allowed: {sorted(VALID_EXIT_COMBINATIONS)}"
        )


def submit_market_sell(
    ticker: str,
    qty: int,
    http: httpx.Client,
    api_key: str,
    *,
    venue_code: str,
    time_in_force: str = "DAY",
) -> dict[str, Any]:
    """POST /api/v2/orders with a single SELL MARKET.

    Phase 4.1: validates the (order_type, time_in_force) combination
    before any HTTP I/O. Calls passing market+OPG (the 2026-05-15
    bug) raise immediately instead of round-tripping a 4xx from the
    broker."""
    _validate_exit_combination("market", time_in_force)
    body = {
        "apikey": api_key,
        "instrument": {"venue_code": venue_code, "canonical_symbol": ticker},
        "side": "SELL",
        "order_type": "MARKET",
        "quantity": str(qty),
        "quantity_unit": "WHOLE",
        "time_in_force": time_in_force,
    }
    r = http.post("/api/v2/orders",
                  json=body,
                  headers=_api_headers(api_key))
    parsed = r.json() if r.content else {}
    parsed["_http_status"] = r.status_code
    return parsed


def compute_marketable_sell_limit(
    quote_bid: float, offset_pct: float,
) -> float:
    """Phase 4.2: SELL marketable-limit price = bid * (1 - offset).
    A positive offset crosses below the inside bid to ensure a fill
    on a thin book.
    """
    return round(float(quote_bid) * (1.0 - float(offset_pct)), 4)


def submit_marketable_limit_sell(
    ticker: str,
    qty: int,
    http: httpx.Client,
    api_key: str,
    *,
    venue_code: str,
    limit_price: float,
    time_in_force: str = "DAY",
) -> dict[str, Any]:
    """Phase 4.2: SELL LIMIT (default DAY TIF) at the supplied
    marketable price. Mirrors :func:`submit_parent_marketable_limit_buy`
    on the buy side.
    """
    _validate_exit_combination("limit", time_in_force)
    body = {
        "apikey": api_key,
        "instrument": {"venue_code": venue_code, "canonical_symbol": ticker},
        "side": "SELL",
        "order_type": "LIMIT",
        "quantity": str(qty),
        "quantity_unit": "WHOLE",
        "price": str(round(float(limit_price), 4)),
        "time_in_force": time_in_force,
    }
    r = http.post("/api/v2/orders",
                  json=body,
                  headers=_api_headers(api_key))
    parsed = r.json() if r.content else {}
    parsed["_http_status"] = r.status_code
    return parsed


# ---------------------------------------------------------------- cancel


def cancel_order(order_id: str, http: httpx.Client, api_key: str) -> dict[str, Any]:
    """DELETE /api/v2/orders/<id>. Idempotent on 404 / already-closed."""
    if not order_id:
        return {"status": "noop", "reason": "no order_id"}
    # Phase 1.1: header-only auth on DELETE (cancel). The redundant
    # query apikey used to land in proxy access logs.
    r = http.request(
        "DELETE", f"/api/v2/orders/{order_id}",
        headers=_api_headers(api_key),
    )
    parsed = r.json() if r.content else {}
    if r.status_code == 200:
        return {"status": "canceled", "order_id": order_id, "data": parsed}
    if r.status_code == 404:
        LOG.debug("cancel %s: 404 (already gone) — treating as success", order_id)
        return {"status": "canceled", "order_id": order_id, "data": parsed}
    err_msg = ""
    if isinstance(parsed, dict):
        err = parsed.get("error") or {}
        err_msg = (err.get("message") or "").lower()
    if any(k in err_msg for k in (
        "already inactive", "already_inactive",
        "already canceled", "already_canceled",
        "not found", "not_found",
    )):
        LOG.debug("cancel %s: idempotent terminal state — treating as success", order_id)
        return {"status": "canceled", "order_id": order_id, "data": parsed}
    raise RuntimeError(f"cancel_order failed for {order_id}: HTTP {r.status_code} {parsed}")


# ---------------------------------------------------------------- fill polling


@dataclass
class FillEvent:
    ticker: str
    order_id: str
    role: str  # "parent", "target", "stop"
    status: str
    filled_qty: int
    filled_avg_price: float | None
    raw: dict[str, Any]


def _build_order_index(state: State) -> dict[str, tuple[str, str]]:
    """Map order_id -> (ticker, role).

    Phase 3.2 (2026-05-16): only index ``parent_order_id`` when the
    position is in a pre-fill state. Once filled (or further along),
    the parent is terminal and any subsequent broker echo for it
    becomes a duplicate to be suppressed by :func:`_handle_parent_fill`
    rather than reprocessed by ``poll_fills``. Without this guard a
    parent that lingers in the broker's ``/orders?status=all`` window
    re-triggers the parent-fill branch on every poll, corrupting
    MFE/MAE.
    """
    idx: dict[str, tuple[str, str]] = {}
    for ticker, pos in (state.get("open_positions") or {}).items():
        if pos.get("status") in {"pending_entry", "submitted", "pending_fill"}:
            if pid := pos.get("parent_order_id"):
                idx[pid] = (ticker, "parent")
        for role, oid in (pos.get("child_order_ids") or {}).items():
            if oid:
                idx[oid] = (ticker, role)
        if eid := pos.get("exit_order_id"):
            idx[eid] = (ticker, "exit")
    for ticker, pend in (state.get("pending_signal_fade_exits") or {}).items():
        if oid := pend.get("exit_order_id"):
            idx[oid] = (ticker, "exit")
    return idx


# ---------------------------------------------------------------- Phase 3 idempotency helpers


def _initialize_peak_trough_once(pos: dict) -> None:
    """Phase 3.3: set peak / trough to entry_price exactly once per
    position. Subsequent calls are no-ops, even if the price has
    moved — the bug was a duplicate parent-fill reprocessing reset
    peak/trough back to entry_price, corrupting MFE/MAE.
    """
    if pos.get("mfe_mae_initialized"):
        return
    ep = pos.get("entry_price")
    if ep is None:
        return
    try:
        ep_f = float(ep)
    except (TypeError, ValueError):
        return
    pos["peak_since_entry"] = ep_f
    pos["trough_since_entry"] = ep_f
    pos["mfe_mae_initialized"] = True


def _handle_parent_fill(
    ticker: str, pos: dict, ev: "FillEvent", cfg: dict | None,
) -> tuple[bool, list["FillEvent"]]:
    """Process a parent BUY fill exactly once per position.

    Returns ``(dirty, events_to_emit)``. Subsequent calls for the same
    parent order are no-ops with one debug log line.

    Phase 3.3 (2026-05-16): closes the bug class where the broker's
    ``/orders?status=all`` window returns a FILLED parent row on
    every poll, causing the legacy code to repeatedly reset peak /
    trough to entry_price and re-emit entry_fill events.
    """
    order_id = ev.order_id
    event_key = f"{order_id}|parent_fill|{ev.filled_qty}|{ev.status}"

    if pos.get("parent_fill_processed"):
        LOG.debug(
            "duplicate_parent_fill_ignored ticker=%s order_id=%s",
            ticker, order_id,
        )
        return False, []

    if pos.get("status") not in {"pending_entry", "submitted", "pending_fill"}:
        LOG.warning(
            "late_parent_fill_ignored ticker=%s status=%s order_id=%s",
            ticker, pos.get("status"), order_id,
        )
        pos["parent_fill_processed"] = True
        pos["parent_fill_processed_at"] = _now_utc_iso()
        emit_ledger_event(
            cfg, event_type="duplicate_parent_fill_suppressed",
            trade_id=pos.get("link_id"), ticker=ticker,
            payload={"order_id": order_id, "current_status": pos.get("status")},
        )
        return True, []

    proc = pos.setdefault("processed_order_events", {})
    if event_key in proc:
        return False, []

    pos["status"] = "filled"
    pos["entry_price"] = ev.filled_avg_price or pos.get("entry_price")
    if ev.filled_qty > 0:
        pos["qty"] = ev.filled_qty
    pos["parent_fill_processed"] = True
    pos["parent_fill_processed_at"] = _now_utc_iso()
    proc[event_key] = pos["parent_fill_processed_at"]

    _initialize_peak_trough_once(pos)
    _mark_parent_filled_for_protection(pos, cfg)
    emit_entry_fill(cfg, pos=pos, ev=ev)
    return True, [ev]


def _ledger_has_pending_exit(
    cfg: dict | None, key: str, *, scan_last_n: int = 200,
) -> bool:
    """Phase 3.4: True when the canonical ledger contains an
    ``exit_submitted`` / ``replacement_exit_accepted`` /
    ``exit_order_accepted`` event for the given idempotency key in
    the last ``scan_last_n`` entries (one trading day's worth)."""
    if cfg is None or not cfg.get("paths"):
        return False
    try:
        path = _ledger_path(cfg)
    except Exception:
        return False
    if not path.exists():
        return False
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return False
    interesting = {
        "exit_submitted",
        "replacement_exit_accepted",
        "exit_order_accepted",
    }
    for raw in lines[-scan_last_n:]:
        raw = raw.strip()
        if not raw:
            continue
        try:
            ev = json.loads(raw)
        except ValueError:
            continue
        if ev.get("event_type") not in interesting:
            continue
        payload = ev.get("payload") or {}
        if payload.get("exit_idempotency_key") == key:
            return True
    return False


_FILLED = {"filled", "FILLED"}
_PENDING = {"new", "accepted", "pending_new", "pending", "partially_filled",
            "NEW", "ACCEPTED", "PENDING_NEW", "PARTIALLY_FILLED"}
_DEAD = {"canceled", "cancelled", "rejected", "expired", "replaced",
         "CANCELED", "CANCELLED", "REJECTED", "EXPIRED", "REPLACED",
         "done_for_day", "DONE_FOR_DAY"}


# ---------------------------------------------------------------- Phase 6 OrderStreamClient


class OrderStreamClient:
    """Phase 6.1: optional event-driven order updates.

    Subscribes to a broker-side SSE-style stream of order events and
    pushes broker-row dicts onto an internal queue. ``poll_fills``
    drains the queue at the start of each tick, feeding events
    through the same idempotency layer as the legacy poll. The
    polling path remains for reconciliation: any order ID surfaced
    by the poll that the stream didn't see increments the missed-
    event recovery counter.

    Default-off: instantiated only when
    ``cfg.broker.stream.enabled`` is true. The legacy
    ``poll_fills(stream_client=None)`` path is unchanged when the
    feature is off — no behavior delta until the operator flips
    the flag.

    Tests inject events directly via :meth:`push_test_event` so we
    never need a real SSE server in the test harness.
    """

    def __init__(self, cfg: dict, api_key: str):
        self._cfg = cfg
        self._api_key = api_key
        stream_cfg = ((cfg.get("broker") or {}).get("stream") or {})
        self._endpoint = stream_cfg.get("endpoint", "/api/v2/orders/stream")
        self._reconnect_max = float(
            stream_cfg.get("reconnect_max_backoff_seconds") or 30,
        )
        self._reconnect_initial = float(
            stream_cfg.get("reconnect_initial_backoff_seconds") or 1,
        )
        self._max_consec_failures = int(
            stream_cfg.get("max_consecutive_failures") or 5,
        )
        self._lag_warning_s = float(
            stream_cfg.get("lag_warning_seconds") or 5,
        )
        self._lag_severe_s = float(
            stream_cfg.get("lag_severe_seconds") or 30,
        )
        self._queue: list[dict] = []
        self._connected = False
        self._last_event_at: datetime | None = None
        self._reconnect_count = 0
        self._consec_failures = 0
        self._failed_total = 0
        self._stopped = False
        self._missed_events_recovered_by_poll = 0
        # Per-tick delta of missed events. Read+reset by stats().
        self._missed_delta = 0

    def start(self) -> None:
        """Mark the client as connected. Real SSE connection logic is
        out of scope for the default-off scaffold; subclasses or
        future versions may override."""
        self._connected = True
        self._stopped = False

    def stop(self) -> None:
        self._connected = False
        self._stopped = True

    def push_test_event(self, row: dict) -> None:
        """Test hook: enqueue a broker-row dict the next drain will
        deliver. Production code uses an internal background thread
        for this."""
        self._queue.append(row)
        self._last_event_at = datetime.now(timezone.utc)

    def drain(self) -> list[dict]:
        out = list(self._queue)
        self._queue.clear()
        return out

    def record_recovered(self, n: int) -> None:
        """Called by ``poll_fills`` when a polled order ID was NOT
        previously surfaced by the stream — counts as a missed
        event that the poll had to recover."""
        self._missed_events_recovered_by_poll += int(n)
        self._missed_delta += int(n)

    def record_failure(self) -> None:
        """Mark one connection failure. After max_consecutive_failures
        the client logs a ``stream_failed`` event and stops."""
        self._consec_failures += 1
        self._failed_total += 1
        if self._consec_failures >= self._max_consec_failures and not self._stopped:
            self._stopped = True
            self._connected = False
            emit_ledger_event(
                self._cfg, event_type="stream_failed",
                trade_id=None, ticker=None,
                payload={
                    "consecutive_failures": self._consec_failures,
                    "total_failures": self._failed_total,
                    "reconnect_count": self._reconnect_count,
                },
            )

    def record_reconnect_success(self) -> None:
        """Reset the consecutive-failure counter when a reconnect
        attempt succeeds."""
        self._reconnect_count += 1
        self._consec_failures = 0
        self._connected = True

    def stats(self) -> dict[str, Any]:
        now = datetime.now(timezone.utc)
        lag = None
        if self._last_event_at is not None:
            lag = max(0.0, (now - self._last_event_at).total_seconds())
        stats = {
            "connected": bool(self._connected),
            "last_event_at": (
                self._last_event_at.isoformat()
                if self._last_event_at else None
            ),
            "lag_seconds": lag,
            "missed_events_recovered_by_poll": self._missed_delta,
            "reconnect_count": self._reconnect_count,
        }
        self._missed_delta = 0
        return stats

    @property
    def stopped(self) -> bool:
        return self._stopped


def emit_stream_health(
    cfg: dict | None, stream_client: "OrderStreamClient",
) -> None:
    """Phase 6.3: emit a stream_health row each loop tick when
    streaming is enabled. ``poll_fills`` is the natural call site
    but we keep the helper separate so the main loop can invoke
    it even on ticks that skipped poll_fills."""
    if cfg is None:
        return
    s = stream_client.stats()
    emit_ledger_event(
        cfg, event_type="stream_health",
        trade_id=None, ticker=None,
        payload=s,
    )


def _process_order_rows(
    rows: list[dict],
    state: State,
    cfg: dict | None,
) -> tuple[bool, list[FillEvent]]:
    """Phase 6.2: shared order-row processing used by both
    :func:`poll_fills` and the order stream drainer. Walks each row,
    routes it through the appropriate fill handler, and returns
    ``(dirty, events)``. Side-effects (state mutation, ledger
    emissions) are identical to the legacy poll path because both
    transports share the Phase 3 idempotency layer
    (``processed_order_events`` per position)."""
    idx = _build_order_index(state)
    events: list[FillEvent] = []
    dirty = False
    open_positions = state.setdefault("open_positions", {})

    for row in rows:
        oid = row.get("id") or row.get("order_id") or ""
        if oid not in idx:
            continue
        ticker, role = idx[oid]
        status = row.get("native_status") or row.get("status") or ""
        canonical = (row.get("canonical_status") or status).upper()
        filled_qty = int(float(
            row.get("filled_qty") or row.get("filled_quantity") or 0,
        ))
        filled_avg = row.get("filled_avg_price")
        try:
            filled_avg_f = float(filled_avg) if filled_avg is not None else None
        except (ValueError, TypeError):
            filled_avg_f = None
        ev = FillEvent(
            ticker=ticker, order_id=oid, role=role,
            status=canonical, filled_qty=filled_qty,
            filled_avg_price=filled_avg_f, raw=row,
        )

        pos = open_positions.get(ticker)

        if role == "parent" and pos is not None:
            if status in _FILLED or canonical == "FILLED":
                pos_dirty, new_events = _handle_parent_fill(
                    ticker, pos, ev, cfg,
                )
                if pos_dirty:
                    dirty = True
                events.extend(new_events)
            elif status in _DEAD or canonical in {s.upper() for s in _DEAD}:
                if filled_qty > 0:
                    pos_dirty, new_events = _handle_parent_fill(
                        ticker, pos, ev, cfg,
                    )
                    if pos_dirty:
                        dirty = True
                    events.extend(new_events)
                    LOG.warning(
                        "parent %s ended in %s with partial fill %d shares",
                        ticker, canonical, filled_qty,
                    )
                else:
                    open_positions.pop(ticker, None)
                    LOG.info(
                        "parent %s ended in %s — position dropped",
                        ticker, canonical,
                    )
                    emit_order_event(
                        cfg, pos=pos, role="parent_terminal", ev=ev,
                    )
                    dirty = True
                    events.append(ev)

        elif role in ("target", "stop") and pos is not None:
            if status in _FILLED or canonical == "FILLED":
                pos.setdefault("filled_children", {})[role] = {
                    "filled_qty": filled_qty,
                    "filled_avg_price": filled_avg_f,
                }
                dirty = True
                events.append(ev)
                emit_order_event(cfg, pos=pos, role=role, ev=ev)

        elif role == "exit" and pos is not None:
            if status in _FILLED or canonical == "FILLED":
                pos["exit_fill_price"] = filled_avg_f
                pos["exit_filled_qty"] = filled_qty
                dirty = True
                events.append(ev)
                emit_order_event(cfg, pos=pos, role="exit", ev=ev)

    return dirty, events


def poll_fills(
    state: State,
    http: httpx.Client,
    api_key: str,
    *,
    state_path: Path,
    cfg: dict | None = None,
    stream_client: "OrderStreamClient | None" = None,
) -> list[FillEvent]:
    """GET /api/v2/orders?status=all and reconcile fills against state.

    Phase 6 (2026-05-16): when ``stream_client`` is provided, the
    stream's queue is drained first and any stream-delivered events
    flow through ``_process_order_rows`` (sharing the idempotency
    layer with the poll path). The poll then runs as before so
    missed events are recovered.

    Updates state in place and persists on any change. Returns the
    list of detected fill events for the caller.
    """
    if not state.get("open_positions") and not state.get("pending_signal_fade_exits"):
        return []

    events: list[FillEvent] = []
    dirty = False

    # Phase 6.2 — drain the stream first.
    seen_via_stream: set[str] = set()
    if stream_client is not None:
        try:
            stream_rows = stream_client.drain()
        except Exception as e:
            LOG.warning("stream drain raised (continuing on poll): %s", e)
            stream_rows = []
        for r in stream_rows:
            oid = r.get("id") or r.get("order_id") or ""
            if oid:
                seen_via_stream.add(oid)
        sd, se = _process_order_rows(stream_rows, state, cfg)
        dirty = dirty or sd
        events.extend(se)

    # Phase 1.1: header-only auth on GET; keep ``status=all`` query.
    r = http.get("/api/v2/orders",
                 headers=_api_headers(api_key),
                 params={"status": "all"})
    r.raise_for_status()
    body = r.json().get("data") or {}
    rows = body.get("orders") or []
    pd_, pe = _process_order_rows(rows, state, cfg)
    dirty = dirty or pd_
    events.extend(pe)

    if stream_client is not None:
        # Count IDs that the poll surfaced but the stream missed.
        poll_ids = {(row.get("id") or row.get("order_id") or "") for row in rows}
        poll_ids.discard("")
        missed = poll_ids - seen_via_stream
        if missed:
            stream_client.record_recovered(len(missed))

    open_positions = state.setdefault("open_positions", {})

    # Phase 6.3 — marketable-limit timeout. Walk pending_fill
    # positions whose entry_order_style is marketable_limit; cancel
    # the order and free the slot when timeout has elapsed without a
    # fill.
    if cfg is not None:
        timeout_s = float(
            (cfg.get("entry") or {}).get("marketable_limit_timeout_seconds")
            or 0
        )
        if timeout_s > 0:
            now = datetime.now(timezone.utc)
            for ticker, pos in list(open_positions.items()):
                if pos.get("status") != "pending_fill":
                    continue
                if pos.get("entry_order_style") != "marketable_limit":
                    continue
                ts = pos.get("entry_timestamp")
                if not ts:
                    continue
                try:
                    sub_dt = datetime.fromisoformat(
                        ts.replace("Z", "+00:00")
                    )
                except Exception:
                    continue
                if sub_dt.tzinfo is None:
                    sub_dt = sub_dt.replace(tzinfo=timezone.utc)
                if (now - sub_dt).total_seconds() < timeout_s:
                    continue
                parent_id = pos.get("parent_order_id")
                if parent_id:
                    try:
                        cancel_order(parent_id, http, api_key)
                    except Exception as e:
                        LOG.exception(
                            "marketable_limit_timeout cancel failed for %s: %s",
                            ticker, e,
                        )
                emit_ledger_event(
                    cfg, event_type="missed_trade",
                    trade_id=pos.get("link_id"),
                    ticker=ticker,
                    payload={
                        "reason": "marketable_limit_timeout",
                        "entry_limit_price": pos.get("entry_limit_price"),
                        "entry_timestamp": ts,
                        "elapsed_seconds": (now - sub_dt).total_seconds(),
                    },
                )
                open_positions.pop(ticker, None)
                dirty = True
                LOG.warning(
                    "marketable_limit_timeout: %s (limit=%.4f) — order canceled, slot freed",
                    ticker, float(pos.get("entry_limit_price") or 0),
                )

    if dirty:
        save_state(state, state_path)

    return events


# ---------------------------------------------------------------- exits


# Allowed exit reasons (closure taxonomy).
EXIT_REASONS = {
    "stop_hit", "target_hit", "time_stop", "signal_fade",
    "kill_switch_l2", "kill_switch_l3", "closed_externally",
    # Phase 5 reserves these labels; tests in Phase 3 may not see
    # them yet but the set is the canonical reasons surface.
    "protection_violation_flatten",
}


def should_set_rescreen_pending(
    reason: str, state: State, cfg: dict,
) -> bool:
    """Phase 3.2 — fail-closed rescreen gating.

    Returns True only when ALL the following hold:
    * post_closure_rescreen.enabled is True.
    * If ``only_after_reasons`` is set, the closure reason is one of
      the allowed labels (fail-closed: an unrecognised reason yields
      False).
    * If ``require_day_pnl_nonnegative`` is True, today's realized
      PnL is >= 0.
    * If ``max_stopouts_today`` is set, today's stopout count is
      below it.
    * If ``max_entries_per_day`` is set, today's rescreen entries
      count is below it.

    Any missing ``only_after_reasons`` set (or empty list) is a
    fail-closed signal: do not rescreen. Operators must explicitly
    opt in by listing allowed reasons (typically just
    ``["target_hit"]``).
    """
    rc_cfg = (cfg.get("entry") or {}).get("post_closure_rescreen") or {}
    if not rc_cfg.get("enabled"):
        return False
    allow = rc_cfg.get("only_after_reasons")
    if allow is None or not list(allow):
        # Fail-closed default per Report §8.4.
        return False
    if reason not in set(allow):
        return False
    if rc_cfg.get("require_day_pnl_nonnegative"):
        pnl = float(state.get("daily_realized_pnl_strategy") or 0.0)
        if pnl < 0:
            return False
    cap_stops = rc_cfg.get("max_stopouts_today")
    if cap_stops is not None:
        if int(state.get("daily_stopouts_count", 0)) >= int(cap_stops):
            return False
    cap_entries = rc_cfg.get("max_entries_per_day")
    if cap_entries is not None:
        if int(state.get("post_closure_entries_today", 0)) >= int(cap_entries):
            return False
    return True


def update_daily_closure_risk_state(
    state: State, cfg: dict, *, reason: str, realized_pnl: float,
) -> None:
    """Phase 3.5 — update circuit-breaker counters after a closure.

    Called from :func:`close_position` after the closure record is
    appended but BEFORE save_state. Mutates state in place; the
    caller is responsible for persistence.

    Counters:
      * ``daily_stopouts_count`` — cumulative count of ``stop_hit``
        closures today. Incremented only on stop_hit.
      * ``consecutive_stopouts_count`` — streak of ``stop_hit``
        closures. Resets on target_hit / time_stop / signal_fade /
        closed_externally (any non-stop close).
      * ``daily_realized_pnl_strategy`` / ``daily_realized_pnl_
        bankroll_pct`` — running sum for the day; the second is the
        first divided by current bankroll (or 1.0 to avoid divide-
        by-zero when bankroll is disabled).

    Trip the block flag when any of the cfg.risk caps cross.
    """
    if reason == "stop_hit":
        state["daily_stopouts_count"] = int(state.get("daily_stopouts_count", 0)) + 1
        state["consecutive_stopouts_count"] = int(
            state.get("consecutive_stopouts_count", 0)
        ) + 1
    elif reason in {
        "target_hit", "time_stop", "signal_fade", "closed_externally",
        "protection_violation_flatten",
    }:
        state["consecutive_stopouts_count"] = 0

    pnl = float(state.get("daily_realized_pnl_strategy") or 0.0) + float(realized_pnl)
    state["daily_realized_pnl_strategy"] = pnl
    bk = (state.get("bankroll") or {}).get("current_dollars") or 0.0
    if bk and bk > 0:
        state["daily_realized_pnl_bankroll_pct"] = pnl / float(bk)

    risk_cfg = cfg.get("risk") or {}

    def _block(why: str) -> None:
        # Only ratchet (never un-block) so the first reason to fire
        # remains the audit-visible cause.
        if not state.get("block_new_entries_today"):
            state["block_new_entries_today"] = True
            state["new_entries_blocked_reason"] = why
            LOG.warning(
                "circuit-breaker tripped: block_new_entries_today=True, reason=%s",
                why,
            )

    cap_stops = risk_cfg.get("max_stopouts_per_day")
    if cap_stops is not None and int(state["daily_stopouts_count"]) >= int(cap_stops):
        _block("max_stopouts_per_day")

    cap_streak = risk_cfg.get("stop_trading_after_consecutive_stopouts")
    if cap_streak is not None and int(state["consecutive_stopouts_count"]) >= int(cap_streak):
        _block("consecutive_stopouts")

    # daily_loss_pct already trips daily_pnl_tripped via
    # update_daily_pnl on equity ticks. Mirror that signal into the
    # block flag so the entry path treats both as the same gate.
    if state.get("daily_pnl_tripped"):
        _block("daily_pnl_tripped")

    # Phase 3.4 — strategy_slice_loss_pct trip.
    slice_loss_pct = risk_cfg.get("strategy_slice_loss_pct")
    if slice_loss_pct is not None:
        # daily_realized_pnl_bankroll_pct compares against the full
        # bankroll. For a slice-based check, compare against the
        # daily slice (bankroll / max_hold_days). When bankroll is
        # off, the slice = 1.0 sentinel which makes the trip
        # impossible (correct fail-soft behavior).
        bk_dollars = (state.get("bankroll") or {}).get("current_dollars")
        if bk_dollars and bk_dollars > 0:
            exits_cfg = cfg.get("exits") or {}
            max_hold = max(1, int(exits_cfg.get("max_hold_days") or 1))
            slice_basis = float(bk_dollars) / float(max_hold)
            if slice_basis > 0:
                slice_pct = pnl / slice_basis
                if slice_pct <= -float(slice_loss_pct):
                    _block("strategy_slice_loss")


def trading_days_since(entry_iso: str, today_et: date) -> int:
    """Number of NYSE trading days between entry's ET date and today_et,
    counted as days *elapsed* (entry day = 0)."""
    entry_dt = datetime.fromisoformat(entry_iso.replace("Z", "+00:00"))
    entry_date = _to_eastern(entry_dt).date()
    if entry_date >= today_et:
        return 0
    sched = _NYSE.schedule(start_date=entry_date, end_date=today_et)
    if sched.empty:
        return 0
    # The schedule includes both entry_date and today_et; "elapsed
    # trading days" excludes the entry day itself.
    return max(0, len(sched) - 1)


def _revert_exit_pending(
    pos: dict[str, Any],
    state: State,
    state_path: Path,
) -> None:
    """Roll back the dedup reservation that ``trigger_time_stop`` placed
    on a position when the exit submission fails. Returning the status
    to ``"filled"`` re-arms the position for the next pass to retry."""
    pos["status"] = "filled"
    pos.pop("exit_reason_pending", None)
    pos.pop("exit_pending_at", None)
    save_state(state, state_path)


def trigger_time_stop(
    ticker: str,
    pos: dict[str, Any],
    cfg: dict,
    http: httpx.Client,
    api_key: str,
    *,
    state: State,
    state_path: Path,
    reason: str = "time_stop",
    time_in_force: str = "DAY",
) -> None:
    """Cancel both OCO children, submit a market sell, mark the position
    as exiting. Idempotent on cancel: a child already filled (404) is
    treated as success so the market sell still goes out.

    Dedup guard (2026-05-15 incident): this function's network I/O
    (cancel children + submit_market_sell) can outlast a single
    ``loop_interval_seconds`` tick. Before the guard, two back-to-back
    intraday-loop iterations could both enter the function for the same
    ticker before the first reached the ``status = "exiting"`` mutation,
    causing the market-sell to fire twice and (in the live incident)
    opening an unintended short. The guard at the top reserves a
    transient ``"exit_pending"`` status BEFORE any I/O and persists it
    immediately, so the caller-level filter
    (``pos.get("status") != "filled"`` in run_time_stop_pass and
    siblings) and this function's own mirrored check both exclude the
    position from re-firing. On any error path the status is reverted
    to ``"filled"`` so the next pass can retry."""
    # Phase 4.5 — assert allowable TIF. Marketable-limit signal-fade
    # exits route through replace_protection_with_exit, not through
    # this function. The only legitimate values here are DAY and
    # GTC (max-hold time stop, kill-switch flattens).
    if time_in_force not in {"DAY", "GTC"}:
        raise ValueError(
            f"trigger_time_stop: unsupported time_in_force={time_in_force!r} "
            "(allowed: DAY, GTC)"
        )

    # ---- Dedup guard ----------------------------------------------------
    # Mirror the caller's ``status == "filled"`` filter here too, so
    # any future caller that forgets to filter (or a race where the
    # caller-side check passed before the first exit reserved the
    # slot) is still safe.
    if pos.get("status") != "filled":
        LOG.info(
            "exit for %s already in flight (status=%s, reason=%s); "
            "not re-triggering",
            ticker,
            pos.get("status"),
            pos.get("exit_reason") or pos.get("exit_reason_pending") or "?",
        )
        return

    # Phase 3.4 — exit idempotency key. The same position + reason +
    # entry_date should never produce two market-sell submissions. The
    # transient status-flip dedup catches in-process double-fires, but
    # a process restart mid-exit (or any future caller that bypasses
    # the status guard) is still vulnerable. Scan the canonical
    # ledger for a matching key before submitting.
    key = pos.get("exit_idempotency_key")
    if key is None:
        entry_date = (pos.get("entry_timestamp") or "")[:10]
        key = f"{pos.get('link_id', ticker)}|exit|{reason}|{entry_date}"
        pos["exit_idempotency_key"] = key
    if _ledger_has_pending_exit(cfg, key):
        LOG.warning(
            "trigger_time_stop: exit suppressed by idempotency key %s",
            key,
        )
        return

    # Reserve the slot BEFORE any network I/O. The intraday loop fires
    # every ``loop_interval_seconds`` (default 5s); cancel + submit can
    # take longer than that, so without this reservation a second tick
    # would see ``status == "filled"`` and re-enter.
    pos["status"] = "exit_pending"
    pos["exit_reason_pending"] = reason
    pos["exit_pending_at"] = datetime.now(timezone.utc).isoformat()
    save_state(state, state_path)
    # ---------------------------------------------------------------------

    LOG.info("Triggering exit (%s) for %s qty=%d",
             reason, ticker, pos.get("qty"))
    children = pos.get("child_order_ids") or {}
    for role in ("target", "stop"):
        oid = children.get(role)
        if not oid:
            continue
        try:
            cancel_order(oid, http, api_key)
        except Exception as e:
            LOG.warning("cancel %s child %s failed (continuing): %s",
                        ticker, role, e)
    venue_code = pos.get("venue_code") or cfg["sizing"]["default_venue_code"]
    try:
        resp = submit_market_sell(
            ticker, int(pos["qty"]), http, api_key,
            venue_code=venue_code, time_in_force=time_in_force,
        )
    except Exception as e:
        LOG.exception("market-sell submission failed for %s: %s", ticker, e)
        _revert_exit_pending(pos, state, state_path)
        return

    # Item 7 fix: a 4xx/5xx from /api/v2/orders does NOT raise from
    # submit_market_sell — it returns a parsed body with
    # ``_http_status`` set. We must validate before mutating state.
    # The previous code blindly set status="exiting" with whatever
    # exit_id it could parse (often ""), stranding the position so
    # the next time-stop / signal-fade pass would skip it on
    # ``status != "filled"``.
    http_status = (resp or {}).get("_http_status") if isinstance(resp, dict) else None
    if http_status not in (200, 201):
        LOG.error(
            "market-sell rejected for %s (status=%s); reverting to "
            "'filled' so the next pass can retry: %s",
            ticker, http_status, resp,
        )
        _revert_exit_pending(pos, state, state_path)
        return

    data = (resp.get("data") or {}) if isinstance(resp, dict) else {}
    exit_id = data.get("order_id") or data.get("id") or ""
    if not exit_id:
        LOG.error(
            "market-sell accepted for %s but no order_id surfaced; "
            "reverting to 'filled' so the next pass can retry: %s",
            ticker, resp,
        )
        _revert_exit_pending(pos, state, state_path)
        return

    pos["status"] = "exiting"
    pos["exit_reason"] = reason
    pos["exit_order_id"] = exit_id
    pos["exit_submitted_at"] = datetime.now(timezone.utc).isoformat()
    # Clear the transient reservation fields now that the broker has
    # ack'd — ``exit_reason`` / ``exit_submitted_at`` / ``exit_order_id``
    # are the canonical "exit in flight" markers from here on.
    pos.pop("exit_reason_pending", None)
    pos.pop("exit_pending_at", None)
    if reason == "signal_fade":
        state.setdefault("pending_signal_fade_exits", {})[ticker] = {
            "submitted_at": pos["exit_submitted_at"],
            "exit_order_id": exit_id,
        }
    # Phase 3.4 — emit an exit_submitted event with the idempotency
    # key so re-runs (or future callers) can detect the duplicate.
    emit_ledger_event(
        cfg, event_type="exit_submitted",
        trade_id=pos.get("link_id"), ticker=ticker,
        payload={
            "exit_order_id": exit_id,
            "reason": reason,
            "exit_idempotency_key": pos.get("exit_idempotency_key"),
            "time_in_force": time_in_force,
        },
    )
    save_state(state, state_path)


def run_time_stop_pass(
    cfg: dict,
    state: State,
    http: httpx.Client,
    api_key: str,
    *,
    today_et: date,
    state_path: Path,
) -> list[str]:
    """Iterate filled positions; trigger time-stop when entry is
    ``max_hold_days`` trading days behind today. Returns the list of
    tickers that were time-stopped this pass."""
    max_hold = int(cfg["exits"]["max_hold_days"])
    out: list[str] = []
    open_positions = dict(state.get("open_positions") or {})
    for ticker, pos in open_positions.items():
        if pos.get("status") != "filled":
            continue
        elapsed = trading_days_since(pos.get("entry_timestamp", ""), today_et)
        if elapsed >= max_hold:
            trigger_time_stop(
                ticker, pos, cfg, http, api_key,
                state=state, state_path=state_path,
                reason="time_stop", time_in_force="DAY",
            )
            out.append(ticker)
    if out:
        # Time-stop frees capacity; let the post-closure rescreen pick
        # up the slack at end-of-tick. The actual exit fill happens
        # async (market sell) and a later poll_fills tick will see it
        # too — that closure also sets rescreen_pending, so this set
        # here just speeds up the first redeployment by one tick.
        #
        # Phase 3.2 — fail-closed: only flip the flag when the
        # operator's rescreen config admits ``time_stop`` as a
        # rescreen-eligible reason.
        if should_set_rescreen_pending("time_stop", state, cfg):
            state["rescreen_pending"] = True
    return out


# ---------------------------------------------------------------- features
#
# DUPLICATION NOTE — feature math
#
# This is a deliberate copy of the prefilter's ``compute_features``
# scoped to a single ticker. We do NOT refactor the prefilter to share
# a feature module: the prefilter ships its own JSON contract and we
# pin parity via a regression test (see
# tests/strategies/test_bowaka_phase3.py:test_signal_fade_features_match_prefilter).
# Any future drift will break that test.


def canonical_mfe_mae(
    entry_price: float,
    bars,  # list[dict] | pd.DataFrame
    *,
    mark_source: str = "trade_high_low",
) -> dict[str, float]:
    """One canonical MFE/MAE calculator. Used by exit-record sealing,
    closure analysis, and tests.

    ``mark_source`` selects which bar columns to inspect:
      * ``"trade_high_low"`` (default) — bar ``high`` / ``low``,
        matching per-trade tick logs that use trade_last_price as
        mark.
      * ``"mid"`` — bar mid ((open+close)/2) — for execution-quality
        replay where trades happened against quotes.

    Returns a dict with ``mfe_pct``, ``mae_pct``, ``peak``,
    ``trough``. Empty bars or ``entry_price <= 0`` returns all zeros
    so the function is safe to call defensively.
    """
    out = {"mfe_pct": 0.0, "mae_pct": 0.0, "peak": 0.0, "trough": 0.0}
    if entry_price is None or float(entry_price) <= 0:
        return out
    ep = float(entry_price)

    rows: list[dict]
    if isinstance(bars, pd.DataFrame):
        if bars.empty:
            return out
        rows = bars.to_dict("records")
    else:
        rows = list(bars or [])
        if not rows:
            return out

    if mark_source == "mid":
        marks_high = [
            float(((r.get("open") or r.get("close") or 0.0)
                   + (r.get("close") or r.get("open") or 0.0)) / 2.0)
            for r in rows
        ]
        marks_low = marks_high
    else:
        marks_high = [float(r.get("high") or r.get("close") or ep) for r in rows]
        marks_low = [float(r.get("low") or r.get("close") or ep) for r in rows]

    peak = max([ep, *marks_high])
    trough = min([ep, *marks_low])
    out["peak"] = peak
    out["trough"] = trough
    out["mfe_pct"] = (peak - ep) / ep
    out["mae_pct"] = (trough - ep) / ep
    return out


def compute_features_single(bars: pd.DataFrame, cfg: dict) -> dict[str, float]:
    """Single-ticker version of the prefilter's compute_features.

    ``bars`` is a DataFrame indexed by date (or with a ``timestamp`` /
    ``ts`` column) with lowercase OHLCV columns. Returns a dict with
    every gate-checked feature plus ``close``.
    """
    if bars.empty:
        return {}
    df = bars.copy()
    if "timestamp" not in df.columns:
        if df.index.name in ("timestamp", "ts", "date") or isinstance(df.index, pd.DatetimeIndex):
            df = df.reset_index().rename(columns={df.index.name or "index": "timestamp"})
        elif "ts" in df.columns:
            df = df.rename(columns={"ts": "timestamp"})
    df = df.sort_values("timestamp").reset_index(drop=True)

    lookback = int(cfg["indicators"]["lookback_days"])
    atr_n = int(cfg["indicators"]["atr_days"])
    ema_n = int(cfg["indicators"]["ema_days"])
    slope_lb = int(cfg["indicators"]["ema_slope_lookback"])

    df["dollar_volume"] = df["close"] * df["volume"]
    df["avg_dollar_volume"] = df["dollar_volume"].shift(1).rolling(lookback).mean()
    df["avg_volume"] = df["volume"].shift(1).rolling(lookback).mean()
    df["rvol"] = df["volume"] / df["avg_volume"]

    df["prev_close"] = df["close"].shift(1)
    tr = pd.concat([
        df["high"] - df["low"],
        (df["high"] - df["prev_close"]).abs(),
        (df["low"] - df["prev_close"]).abs(),
    ], axis=1).max(axis=1)
    df["atr"] = tr.rolling(atr_n).mean()
    df["atr_pct"] = df["atr"] / df["close"]

    df["gap_pct"] = df["open"] / df["prev_close"] - 1.0
    df["range_expansion"] = (df["high"] - df["low"]) / df["atr"]

    rng = (df["high"] - df["low"]).replace(0, np.nan)
    df["close_location"] = ((df["close"] - df["low"]) / rng).fillna(0.5)

    df["ema"] = df["close"].ewm(span=ema_n, adjust=False).mean()
    df["ema_distance"] = df["close"] / df["ema"] - 1.0
    df["ema_lagged"] = df["ema"].shift(slope_lb)
    df["ema_slope"] = df["ema"] / df["ema_lagged"] - 1.0

    last = df.iloc[-1]
    out = {}
    for k in ("close", "rvol", "atr_pct", "range_expansion",
              "close_location", "ema_distance", "ema_slope",
              "avg_dollar_volume", "gap_pct"):
        v = last.get(k)
        out[k] = float(v) if v is not None and not pd.isna(v) else None
    return out


def signal_passes_gates(features: dict[str, float | None], cfg: dict) -> bool:
    """All non-null gates from cfg.signal_gates must pass on the
    feature dict. A null gate is disabled (skipped)."""
    gates = cfg.get("signal_gates", {}) or {}
    spec = [
        ("rvol_min", "rvol"),
        ("atr_pct_min", "atr_pct"),
        ("range_expansion_min", "range_expansion"),
        ("close_location_min", "close_location"),
        ("ema_distance_min", "ema_distance"),
        ("ema_slope_min", "ema_slope"),
    ]
    for cfg_key, feat_key in spec:
        thr = gates.get(cfg_key)
        if thr is None:
            continue
        val = features.get(feat_key)
        if val is None or val < thr:
            return False
    return True


# Phase 4.3 — fade-score components. Each entry is
# (component_name, gate_cfg_key, feature_key). Adding a component
# is allowed (defaults to equal weight). Renaming is breaking.
_FADE_COMPONENTS: list[tuple[str, str, str]] = [
    ("rvol_below_min",            "rvol_min",            "rvol"),
    ("atr_pct_below_min",         "atr_pct_min",         "atr_pct"),
    ("range_expansion_below_min", "range_expansion_min", "range_expansion"),
    ("close_location_below_min",  "close_location_min",  "close_location"),
    ("ema_distance_below_min",    "ema_distance_min",    "ema_distance"),
    ("ema_slope_negative",        "ema_slope_min",       "ema_slope"),
]


def compute_fade_score(
    features: dict[str, float | None], cfg: dict,
) -> tuple[float, dict[str, bool]]:
    """Phase 4.3: Score in [0, 1]. Higher = stronger fade.

    Each component checks one of the cfg.signal_gates against the
    feature. ``True`` in the result dict means the component is in
    a *failed* state (the gate is broken). When the gate's threshold
    is null the component is skipped (does not contribute to the
    score). Weights are read from
    ``cfg.exits.signal_fade.score_weights`` (defaults to equal).
    Returns ``(score, component_results)``.
    """
    sf_cfg = ((cfg.get("exits") or {}).get("signal_fade") or {})
    weights = sf_cfg.get("score_weights") or {}
    gates = cfg.get("signal_gates", {}) or {}

    component_results: dict[str, bool] = {}
    contrib_weight = 0.0
    fail_weight = 0.0
    for name, gate_key, feat_key in _FADE_COMPONENTS:
        thr = gates.get(gate_key)
        if thr is None:
            continue
        val = features.get(feat_key)
        failed = (val is None) or (float(val) < float(thr))
        component_results[name] = bool(failed)
        w = float(weights.get(name) if weights else 1.0)
        contrib_weight += w
        if failed:
            fail_weight += w
    score = fail_weight / contrib_weight if contrib_weight > 0 else 0.0
    return score, component_results


def fade_score_to_band(score: float, cfg: dict) -> str:
    """Phase 4.3: Map a fade score to {hold|soft|hard|critical}."""
    sf_cfg = ((cfg.get("exits") or {}).get("signal_fade") or {})
    thresholds = sf_cfg.get("score_thresholds") or {}
    soft = float(thresholds.get("soft", 0.34))
    hard = float(thresholds.get("hard", 0.50))
    crit = float(thresholds.get("critical", 0.67))
    if score >= crit:
        return "critical"
    if score >= hard:
        return "hard"
    if score >= soft:
        return "soft"
    return "hold"


# ---------------------------------------------------------------- bars fetch


def fetch_daily_bars_for_signal_fade(
    ticker: str,
    venue_code: str,
    http: httpx.Client,
    api_key: str,
    *,
    lookback_calendar_days: int,
    end: datetime,
) -> pd.DataFrame:
    """POST /api/v2/bars for one ticker, daily timeframe, ~30 calendar
    days back. Returns a DataFrame ordered by timestamp ascending."""
    from datetime import timedelta as _td

    start = end - _td(days=lookback_calendar_days)
    body = {
        "apikey": api_key,
        "instrument": {"venue_code": venue_code, "canonical_symbol": ticker},
        "interval": "1d",
        "start": start.isoformat(),
        "end": end.isoformat(),
    }
    r = http.post("/api/v2/bars",
                  json=body, headers=_api_headers(api_key))
    r.raise_for_status()
    payload = r.json().get("data") or {}
    rows = payload.get("bars") or []
    if not rows:
        return pd.DataFrame()
    df = pd.DataFrame(rows)
    for col in ("open", "high", "low", "close", "volume"):
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce")
    if "ts" in df.columns:
        df["timestamp"] = pd.to_datetime(df["ts"], errors="coerce")
        df = df.drop(columns=["ts"])
    return df.sort_values("timestamp").reset_index(drop=True)


# ---------------------------------------------------------------- signal-fade


def _signal_fade_cfg(cfg: dict) -> dict:
    """Read exits.signal_fade with back-compat for the deprecated
    top-level ``exits.signal_fade_enabled`` flag."""
    sf = ((cfg.get("exits") or {}).get("signal_fade") or {})
    if "enabled" not in sf:
        # Honor the deprecated key one more release.
        legacy = (cfg.get("exits") or {}).get("signal_fade_enabled")
        if legacy is not None:
            sf = {**sf, "enabled": bool(legacy)}
    return sf


def _signal_fade_eval_time(cfg: dict) -> str:
    """15:45 ET by default (Phase 4 redesign). Back-compat: read
    ``session.signal_fade_eval_time`` when the new
    ``exits.signal_fade.eval_time`` is unset."""
    sf = _signal_fade_cfg(cfg)
    if t := sf.get("eval_time"):
        return t
    # Back-compat: the legacy session.signal_fade_eval_time was 16:05;
    # respect it when the new key is absent.
    return (cfg.get("session") or {}).get("signal_fade_eval_time", "15:45")


def _signal_fade_telemetry_time(cfg: dict) -> str:
    """16:05 ET by default — log-only run for counterfactual study."""
    sf = _signal_fade_cfg(cfg)
    return sf.get("telemetry_time", "16:05")


def run_signal_fade_pass(
    cfg: dict,
    state: State,
    http: httpx.Client,
    api_key: str,
    *,
    today_et: date,
    state_path: Path,
    now_utc: datetime,
    mode: str = "exit",
) -> list[str]:
    """Phase 4.4: hold-thesis fade evaluation. Two scheduled passes
    per day:

      * ``mode="exit"`` at ``exits.signal_fade.eval_time`` (default
        15:45) — submits a marketable-limit SELL when the band is
        in ``exits.signal_fade.exit_on`` (default {hard, critical}).
      * ``mode="telemetry"`` at ``exits.signal_fade.telemetry_time``
        (default 16:05) — emits ``signal_fade_telemetry`` events for
        the counterfactual ledger. Never submits an order, even
        when ``enabled`` is false.

    Returns the list of tickers that submitted an exit (mode=exit
    only). The telemetry run always returns an empty list.
    """
    sf_cfg = _signal_fade_cfg(cfg)
    marker = f"signal_fade_evaluated_for_date_{mode}"
    if state.get(marker) == today_et.isoformat():
        return []

    # In exit mode the enabled flag gates the actual exit submit. In
    # telemetry mode we run even when enabled is false so the
    # counterfactual study has data.
    exit_mode = (mode == "exit")
    if exit_mode and not sf_cfg.get("enabled", True):
        state[marker] = today_et.isoformat()
        save_state(state, state_path)
        return []

    band_exit_on = set(sf_cfg.get("exit_on") or ["hard", "critical"])
    offset_pct = float(sf_cfg.get("marketable_limit_offset_pct") or 0.005)

    faded: list[str] = []
    open_positions = dict(state.get("open_positions") or {})
    for ticker, pos in open_positions.items():
        if pos.get("status") != "filled":
            continue
        venue_code = pos.get("venue_code") or cfg["sizing"]["default_venue_code"]
        try:
            bars = fetch_daily_bars_for_signal_fade(
                ticker, venue_code, http, api_key,
                lookback_calendar_days=45, end=now_utc,
            )
        except Exception as e:
            LOG.warning(
                "signal_fade bars fetch failed for %s (mode=%s): %s",
                ticker, mode, e,
            )
            continue
        if bars.empty or len(bars) < int(cfg["indicators"]["lookback_days"]):
            LOG.info(
                "signal_fade: insufficient bars for %s (mode=%s) — skipping",
                ticker, mode,
            )
            continue
        feats = compute_features_single(bars, cfg)
        score, gates = compute_fade_score(feats, cfg)
        band = fade_score_to_band(score, cfg)

        emit_ledger_event(
            cfg, event_type="signal_fade_score",
            trade_id=pos.get("link_id"), ticker=ticker,
            payload={
                "mode": mode, "score": score, "band": band,
                "gates": gates, "features": feats,
            },
        )

        if not exit_mode:
            # Telemetry pass — emit the second event and continue.
            emit_ledger_event(
                cfg, event_type="signal_fade_telemetry",
                trade_id=pos.get("link_id"), ticker=ticker,
                payload={
                    "score": score, "band": band, "gates": gates,
                },
            )
            continue

        if band not in band_exit_on:
            continue

        # Phase 4.4 — atomic marketable-limit exit via
        # replace_protection_with_exit. Fetch a quote, compute
        # marketable-limit price, hand a zero-arg callable to the
        # protection helper.
        try:
            qr = http.post(
                "/api/v2/quotes",
                json={
                    "apikey": api_key,
                    "instruments": [{
                        "venue_code": venue_code,
                        "canonical_symbol": ticker,
                    }],
                },
                headers=_api_headers(api_key),
            )
            quote = None
            if qr.status_code == 200:
                rows = (qr.json().get("data") or [])
                if rows:
                    quote = rows[0]
        except Exception as e:
            LOG.warning(
                "signal_fade: quote fetch failed for %s — skipping: %s",
                ticker, e,
            )
            continue
        bid = float((quote or {}).get("bid") or 0.0)
        if bid <= 0:
            LOG.warning(
                "signal_fade: no usable bid for %s; skipping atomic exit",
                ticker,
            )
            continue
        limit_price = compute_marketable_sell_limit(bid, offset_pct)

        def _do_submit(qty=int(pos.get("qty") or 0),
                       _venue=venue_code, _limit=limit_price):
            return submit_marketable_limit_sell(
                ticker, qty, http, api_key,
                venue_code=_venue, limit_price=_limit,
                time_in_force="DAY",
            )

        ok, reason = replace_protection_with_exit(
            ticker, pos, cfg, http, api_key,
            exit_submit_callable=_do_submit,
            state=state, state_path=state_path,
        )
        if ok:
            pos["exit_reason"] = "signal_fade"
            faded.append(ticker)

    state[marker] = today_et.isoformat()
    save_state(state, state_path)
    return faded


# -------------------------------------------------------- daily marks (analytics)


def write_daily_marks(
    cfg: dict,
    state: State,
    http: httpx.Client,
    api_key: str,
    *,
    today_et: date,
    summary_path: Path,
    state_path: Path,
    now_utc: datetime,
) -> list[str]:
    """End-of-session analytic snapshot. For every filled position
    fetch today's daily bar, append a ``daily_mark`` record to the
    daily-summary jsonl, and update the position's
    ``peak_since_entry`` / ``trough_since_entry`` for MFE/MAE
    tracking.

    The record is purpose-built for offline tuning: it carries the
    day's OHLCV, the unrealized P&L at close, the running excursion,
    today's recomputed signal features, and which signal-fade gates
    passed/failed. Combined with the ``opened`` and ``closure``
    records, an analyst can reconstruct the full lifecycle of every
    trade and slice by signal regime, hold duration, gap-at-open,
    etc.

    Idempotent — once-per-day, deduped via
    ``state.daily_marks_written_for_date``. Returns the list of
    tickers that received a mark this call (empty when already
    written today or no filled positions exist).
    """
    today_iso = today_et.isoformat()
    if state.get("daily_marks_written_for_date") == today_iso:
        return []
    open_positions = dict(state.get("open_positions") or {})
    if not open_positions:
        # Nothing to mark, but still set the dedupe so a no-position
        # day doesn't re-attempt every tick.
        state["daily_marks_written_for_date"] = today_iso
        save_state(state, state_path)
        return []

    marked: list[str] = []
    for ticker, pos in open_positions.items():
        if pos.get("status") != "filled":
            continue
        venue_code = pos.get("venue_code") or cfg["sizing"]["default_venue_code"]
        try:
            bars = fetch_daily_bars_for_signal_fade(
                ticker, venue_code, http, api_key,
                lookback_calendar_days=45, end=now_utc,
            )
        except Exception as e:
            LOG.warning(
                "daily_mark bars fetch failed for %s: %s — skipping today",
                ticker, e,
            )
            continue
        if bars.empty:
            LOG.warning("daily_mark: no bars for %s — skipping today", ticker)
            continue

        last = bars.iloc[-1]
        try:
            day_open = float(last.get("open"))
            day_high = float(last.get("high"))
            day_low = float(last.get("low"))
            day_close = float(last.get("close"))
            day_volume = float(last.get("volume"))
        except (TypeError, ValueError):
            LOG.warning(
                "daily_mark: bad bar shape for %s; skipping today", ticker,
            )
            continue

        # Update running peak/trough for MFE/MAE.
        entry_price_v = pos.get("entry_price")
        try:
            entry_price = float(entry_price_v) if entry_price_v is not None else None
        except (TypeError, ValueError):
            entry_price = None
        if entry_price is None or entry_price <= 0:
            LOG.warning(
                "daily_mark: %s has no entry_price yet (status=%s); "
                "writing mark without unrealized pnl",
                ticker, pos.get("status"),
            )
        prev_peak = pos.get("peak_since_entry")
        prev_trough = pos.get("trough_since_entry")
        try:
            prev_peak_f = float(prev_peak) if prev_peak is not None else None
            prev_trough_f = float(prev_trough) if prev_trough is not None else None
        except (TypeError, ValueError):
            prev_peak_f = prev_trough_f = None
        # Default both anchors to entry_price when missing (pre-this-
        # commit positions don't have them); subsequent passes update.
        if prev_peak_f is None and entry_price is not None:
            prev_peak_f = entry_price
        if prev_trough_f is None and entry_price is not None:
            prev_trough_f = entry_price
        new_peak = max(prev_peak_f, day_high) if prev_peak_f is not None else day_high
        new_trough = min(prev_trough_f, day_low) if prev_trough_f is not None else day_low
        pos["peak_since_entry"] = new_peak
        pos["trough_since_entry"] = new_trough

        qty = int(pos.get("qty") or 0)
        unrealized_pnl = (
            (day_close - entry_price) * qty
            if entry_price is not None else None
        )
        unrealized_pnl_pct = (
            (day_close - entry_price) / entry_price
            if entry_price is not None and entry_price > 0 else None
        )
        mfe_dollar = (
            (new_peak - entry_price) * qty
            if entry_price is not None and new_peak is not None else None
        )
        mae_dollar = (
            (new_trough - entry_price) * qty
            if entry_price is not None and new_trough is not None else None
        )

        # Days held since entry (NYSE trading days).
        entry_iso = pos.get("entry_timestamp") or ""
        try:
            days_held = trading_days_since(entry_iso, today_et) if entry_iso else None
        except Exception:
            days_held = None

        # Recompute today's signal features on the fresh bar window
        # so the analyst can see how the signal evolved relative to
        # entry. Skip when not enough history for the prefilter math.
        current_features: dict[str, float] | None = None
        signal_fade_gates: dict[str, dict[str, Any]] | None = None
        if len(bars) >= int(cfg["indicators"]["lookback_days"]):
            try:
                current_features = compute_features_single(bars, cfg)
                # Per-gate breakdown (matches signal_passes_gates).
                gates_cfg = cfg.get("signal_gates", {}) or {}
                spec = [
                    ("rvol_min", "rvol"),
                    ("atr_pct_min", "atr_pct"),
                    ("range_expansion_min", "range_expansion"),
                    ("close_location_min", "close_location"),
                    ("ema_distance_min", "ema_distance"),
                    ("ema_slope_min", "ema_slope"),
                ]
                signal_fade_gates = {}
                for cfg_key, feat_key in spec:
                    thr = gates_cfg.get(cfg_key)
                    val = current_features.get(feat_key)
                    if thr is None:
                        signal_fade_gates[feat_key] = {
                            "value": val, "threshold": None, "passed": True,
                        }
                    else:
                        signal_fade_gates[feat_key] = {
                            "value": val,
                            "threshold": thr,
                            "passed": val is not None and val >= thr,
                        }
            except Exception as e:
                LOG.warning(
                    "daily_mark: feature recompute failed for %s: %s", ticker, e,
                )

        record = {
            "record_type": "daily_mark",
            "ticker": ticker,
            "session_date": today_iso,
            "days_held": days_held,
            "open": day_open,
            "high": day_high,
            "low": day_low,
            "mark_price": day_close,
            "volume": day_volume,
            "qty": qty,
            "entry_price": entry_price,
            "unrealized_pnl": unrealized_pnl,
            "unrealized_pnl_pct": unrealized_pnl_pct,
            "peak_since_entry": new_peak,
            "trough_since_entry": new_trough,
            "mfe_dollar": mfe_dollar,
            "mae_dollar": mae_dollar,
            "target_price": pos.get("target_price"),
            "stop_price": pos.get("stop_price"),
            "current_features": current_features,
            "signal_fade_gates": signal_fade_gates,
            "venue_code": pos.get("venue_code"),
            "exchange": pos.get("exchange"),
            "link_id": pos.get("link_id"),
        }
        try:
            append_closure_record(summary_path, record)
        except Exception as e:
            LOG.exception(
                "could not append daily_mark for %s: %s", ticker, e,
            )
            continue
        marked.append(ticker)
        LOG.info(
            "daily_mark %s d=%s close=%.4f unrealized=%s peak=%.4f trough=%.4f",
            ticker, days_held, day_close,
            f"{unrealized_pnl:.2f}" if unrealized_pnl is not None else "?",
            new_peak, new_trough,
        )

    state["daily_marks_written_for_date"] = today_iso
    save_state(state, state_path)
    return marked


# ---------------------------------------------------------------- closures


def append_closure_record(path: Path, record: dict[str, Any]) -> None:
    """Append a single JSON-Lines record."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "a", encoding="utf-8") as f:
        f.write(json.dumps(record, default=str) + "\n")
        f.flush()


# -------------------------------------------------------- per-trade rich logging
#
# One file per buy, named by link_id. Lives at
#   <daily_summary_path.parent>/trades/<link_id>.jsonl
# Each file is JSONL append-only and carries the full lifecycle of one
# position: entry_decision -> parent_submitted -> entry_fill ->
# bracket_attached -> intraday_tick (many) -> order_event* ->
# exit. Cross-trade analysis stays in daily_summary.jsonl.


def _trade_log_path(cfg: dict, link_id: str) -> Path | None:
    """Per-trade jsonl path. Sibling ``trades/`` dir under the daily-
    summary path's parent. Returns None when link_id is missing
    (defensive — old states without link_id just skip the rich log)."""
    if not link_id:
        return None
    summary_path = _resolve_path(cfg, "daily_summary_path")
    return summary_path.parent / "trades" / f"{link_id}.jsonl"


# ---- Phase 1.5: immutable trade ledger ----
#
# A single append-only JSONL file at
#   <daily_summary_path.parent>/trade_ledger.jsonl
# carries the canonical sequence of trade events. Each event is
# stamped with a fresh ``event_id`` (uuid4 hex) and ``schema_version``.
# Corrections never modify earlier records: a follow-up event with
# ``event_type="correction"`` is appended instead.
#
# Event types currently emitted:
#   * ``entry_decision``    — per-candidate accept / reject record
#                              (twin of the rich per-trade emission).
#   * ``order_submitted``   — parent and bracket-leg submissions.
#   * ``order_fill``        — parent / target / stop fills.
#   * ``closure``           — position closed (any reason).
#   * ``protection_event``  — Phase 5 (reserved; emitter wired here).
#
# The daily summary file (``daily_summary.jsonl``) is reconstructed
# from the ledger via :func:`recompute_daily_summary_from_ledger`.

LEDGER_SCHEMA_VERSION: int = 3

VALID_ENVIRONMENTS: frozenset[str] = frozenset({"paper", "test", "live"})


# ---------------------------------------------------------------- Phase 7.2 — minute-bar storage


def fetch_and_store_candidate_minute_bars(
    cfg: dict,
    candidates: list[dict],
    today_et: date,
    *,
    http: httpx.Client | None = None,
    api_key: str | None = None,
    bars_supplier=None,
) -> Path | None:
    """Phase 7.2: persist minute bars for every candidate so the
    counterfactual engine can replay alternative entry timings after
    the session.

    ``bars_supplier`` is an optional callable
    ``(ticker, venue_code, http, api_key, start_utc, end_utc) -> pd.DataFrame``
    used by tests to substitute synthetic bars. When omitted the
    function POSTs to ``/api/v2/bars`` with a 1-minute interval over
    the configured premarket-to-session-end window.

    Returns the output file path, or None when the feature is
    disabled or no bars were retrieved.
    """
    research_cfg = (cfg.get("research") or {})
    cmb_cfg = (research_cfg.get("candidate_minute_bars") or {})
    if not cmb_cfg.get("enabled"):
        return None
    layout = cmb_cfg.get("layout", "by_session")
    if layout != "by_session":
        LOG.warning(
            "candidate_minute_bars: only layout=by_session is "
            "implemented; got %s — using by_session", layout,
        )
    window = cmb_cfg.get("window") or {}
    pre_start = window.get("premarket_start", "08:00")
    sess_end = window.get("session_end", "16:00")
    import pytz as _pytz
    et = _pytz.timezone("America/New_York")
    sh, sm = (int(x) for x in pre_start.split(":"))
    eh, em = (int(x) for x in sess_end.split(":"))
    start_utc = et.localize(datetime(
        today_et.year, today_et.month, today_et.day, sh, sm,
    )).astimezone(timezone.utc)
    end_utc = et.localize(datetime(
        today_et.year, today_et.month, today_et.day, eh, em,
    )).astimezone(timezone.utc)

    on_missing = cmb_cfg.get("on_missing", "warn").lower()

    out_dir = _ledger_base_dir(cfg) / _strategy_environment(cfg) / "candidate_bars"
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / f"bars_{today_et.isoformat()}.parquet"

    frames: list[pd.DataFrame] = []
    for cand in candidates or []:
        symbol = cand.get("ticker") or cand.get("symbol")
        if not symbol:
            continue
        venue_code = cand.get("venue_code") or "XNAS"
        try:
            if bars_supplier is not None:
                df = bars_supplier(
                    symbol, venue_code, http, api_key, start_utc, end_utc,
                )
            elif http is not None and api_key is not None:
                body = {
                    "apikey": api_key,
                    "instrument": {
                        "venue_code": venue_code,
                        "canonical_symbol": symbol,
                    },
                    "interval": "1m",
                    "start": start_utc.isoformat(),
                    "end": end_utc.isoformat(),
                }
                r = http.post("/api/v2/bars", json=body,
                              headers=_api_headers(api_key))
                r.raise_for_status()
                rows = (r.json().get("data") or {}).get("bars") or []
                df = pd.DataFrame(rows)
            else:
                df = pd.DataFrame()
        except Exception as e:
            if on_missing == "fail":
                raise
            LOG.warning(
                "candidate_minute_bars: fetch failed for %s: %s",
                symbol, e,
            )
            continue
        if df.empty:
            if on_missing == "fail":
                raise RuntimeError(
                    f"empty minute bars for {symbol} on {today_et}"
                )
            if on_missing == "warn":
                LOG.warning(
                    "candidate_minute_bars: empty bars for %s", symbol,
                )
            continue
        df = df.copy()
        df["symbol"] = symbol
        df["session_date"] = today_et.isoformat()
        frames.append(df)

    if not frames:
        return None

    combined = pd.concat(frames, ignore_index=True)
    try:
        combined.to_parquet(out_path, index=False)
    except Exception as e:
        # Fallback to gzipped jsonl when pyarrow is unavailable.
        LOG.warning(
            "candidate_minute_bars: parquet write failed (%s); "
            "falling back to jsonl.gz", e,
        )
        out_path = out_path.with_suffix(".jsonl.gz")
        combined.to_json(out_path, orient="records", lines=True,
                          compression="gzip")
    LOG.info(
        "candidate_minute_bars: wrote %d rows for %d symbols to %s",
        len(combined), combined["symbol"].nunique(), out_path,
    )
    return out_path


def load_catalyst_overrides(cfg: dict) -> dict[tuple[str, str], dict]:
    """Phase 7.5: load operator-curated catalyst metadata from
    ``data/<env>/catalyst_overrides.jsonl``. Returns a dict keyed by
    ``(session_date, symbol)``. Missing file returns an empty dict.
    """
    base = _ledger_base_dir(cfg)
    env = _strategy_environment(cfg)
    path = base / env / "catalyst_overrides.jsonl"
    if not path.exists():
        return {}
    out: dict[tuple[str, str], dict] = {}
    for raw in path.read_text(encoding="utf-8").splitlines():
        raw = raw.strip()
        if not raw:
            continue
        try:
            ev = json.loads(raw)
        except ValueError:
            continue
        sd = ev.get("session_date")
        sym = ev.get("symbol")
        if sd and sym:
            out[(str(sd), str(sym))] = ev
    return out


def _ledger_base_dir(cfg: dict) -> Path:
    """Root of the environment-partitioned ledger tree.

    Resolution order (first that resolves wins):
      1. ``paths.data_dir`` if explicitly set in cfg.
      2. ``<daily_summary_path.parent>`` (the legacy anchor).
    Anchored at the script directory when relative.
    """
    paths = cfg.get("paths") or {}
    explicit_dir = paths.get("data_dir")
    if explicit_dir:
        p = Path(explicit_dir)
        if not p.is_absolute():
            p = Path(__file__).resolve().parent / p
        return p
    summary_path = _resolve_path(cfg, "daily_summary_path")
    return summary_path.parent


def _ledger_path(cfg: dict) -> Path:
    """Resolve the canonical ledger path under ``data/<environment>/``.

    Environment is determined by ``cfg.strategy.environment`` in
    ``{"paper", "test", "live"}``, defaulting to ``"paper"``. The
    legacy flat ``data/trade_ledger.jsonl`` is no longer written;
    archived runs live under ``data/archive/``.

    Operators may still override the path explicitly with
    ``paths.trade_ledger_path`` — useful for one-off reconciliations
    and reports. The override bypasses the environment partition.
    """
    explicit = (cfg.get("paths") or {}).get("trade_ledger_path")
    if explicit:
        p = Path(explicit)
        if not p.is_absolute():
            p = Path(__file__).resolve().parent / p
        return p
    env = _strategy_environment(cfg)
    if env not in VALID_ENVIRONMENTS:
        raise ValueError(
            f"invalid environment: {env!r}; expected one of {sorted(VALID_ENVIRONMENTS)}"
        )
    base = _ledger_base_dir(cfg)
    return base / env / "trade_ledger.jsonl"


def _ledger_session_date(now_utc: datetime | None = None) -> str:
    """ET-local ISO date for the ledger event's ``session_date``."""
    now = now_utc or datetime.now(timezone.utc)
    return _to_eastern(now).date().isoformat()


def emit_ledger_event(
    cfg: dict | None,
    *,
    event_type: str,
    trade_id: str | None,
    ticker: str | None,
    payload: dict[str, Any],
    session_date: str | None = None,
    role: str | None = None,
) -> dict[str, Any] | None:
    """Append a single record to the canonical trade ledger.

    Returns the appended event dict (handy for tests / reconciliation).
    Best-effort — a write failure is logged but does NOT propagate.
    ``cfg=None`` (or any cfg without a ``paths.daily_summary_path``)
    is a no-op (mirrors :func:`_append_trade_log`).

    The ``trade_id`` is typically the position's ``link_id`` — that's
    the join key for ``build_canonical_trade_table`` in Phase 7's
    analysis rewrite. ``role`` is set on order-related events
    (``parent`` / ``target`` / ``stop``) so reports can split by leg.
    """
    if cfg is None or not cfg.get("paths"):
        # No paths.daily_summary_path means no ledger anchor — this
        # is the "reconcile_at_startup with cfg=None" case in older
        # tests. Drop the event quietly rather than crashing.
        return None
    try:
        path = _ledger_path(cfg)
    except Exception as e:
        LOG.warning(
            "ledger path unresolvable (event_type=%s): %s",
            event_type, e,
        )
        return None
    env = _strategy_environment(cfg)
    strategy_id = (cfg.get("strategy") or {}).get("strategy_id") or "bowaka"
    is_test_fixture = bool(
        (cfg.get("strategy") or {}).get("is_test_fixture", False)
    )
    event = {
        "schema_version": LEDGER_SCHEMA_VERSION,
        "event_id": uuid.uuid4().hex,
        "event_type": event_type,
        "ts": _now_utc_iso(),
        "session_date": session_date or _ledger_session_date(),
        "trade_id": trade_id,
        "ticker": ticker,
        "role": role,
        # Phase 1.3: schema v3 envelope. Every event carries enough
        # provenance to be analysed in isolation: which run wrote it,
        # which daemon, which strategy version, which config, which
        # environment. ``analysis_epoch`` is the operator's coarse
        # cut between "old contaminated data" and "post-audit clean".
        "environment": env,
        "is_test_fixture": is_test_fixture,
        "strategy_id": strategy_id,
        "strategy_version": _strategy_version(),
        "analysis_epoch": _analysis_epoch(cfg),
        "run_id": _run_id(env),
        "daemon_instance_id": _daemon_instance_id(),
        "config_hash_full": _config_hash_full(cfg),
        "config_snapshot_path": str(_config_snapshot_path(cfg)),
        "payload": payload,
    }
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "a", encoding="utf-8") as f:
            f.write(json.dumps(event, default=str) + "\n")
            f.flush()
    except Exception as e:
        LOG.warning("ledger append failed (event_type=%s, trade_id=%s): %s",
                    event_type, trade_id, e)
        return None
    return event


def _append_trade_log(cfg: dict | None, link_id: str | None, record: dict[str, Any]) -> None:
    """Append a single record to the per-trade jsonl. Best-effort —
    a write failure does NOT propagate; logging is observability,
    not an order-flow blocker. ``cfg=None`` is a no-op so call sites
    without cfg threading (older tests, ad-hoc utilities) can invoke
    emit_* without scaffolding."""
    if cfg is None:
        return
    path = _trade_log_path(cfg, link_id or "")
    if path is None:
        return
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "a", encoding="utf-8") as f:
            f.write(json.dumps(record, default=str) + "\n")
            f.flush()
    except Exception as e:
        LOG.warning("trade-log append failed (link_id=%s): %s", link_id, e)


def _now_utc_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _safe_float(v: Any) -> float | None:
    try:
        if v is None:
            return None
        return float(v)
    except (TypeError, ValueError):
        return None


# ---- emit_* helpers: each call writes one record to the per-trade jsonl


# Phase 1.4: canonical machine-readable reason labels for the
# universal entry_decision emission. Every rejection point in
# select_entries / filter_by_intraday_confirmation / submit_entry must
# pick one of these. Adding a new label is allowed; renaming an
# existing one is breaking for downstream analytics.
ENTRY_DECISION_REASONS: set[str] = {
    # Accept path
    "accepted",
    # Pre-selection gates (select_entries)
    "already_held",
    "already_entered_today",
    "halt_skip",
    "concurrent_cap",
    "daily_entry_cap",
    "qty_zero",
    "gross_cap",
    # Pre-selection slate-wide blocks
    "kill_switch",
    "daily_pnl_tripped",
    "blocked_by_daily_risk",        # Phase 3
    # Confirmation / quote gates (filter_by_intraday_confirmation)
    "spread_too_wide",
    "quote_stale",
    "bad_quote",
    "chase",
    "failure_band",
    "no_quote",
    # Phase 2
    "excluded_instrument_class",
    # Phase 4 (opening-range / VWAP)
    "opening_range_failed",
    # Phase 6 (marketable limits)
    "marketable_limit_no_quote",
    "marketable_limit_timeout",
    # ADV-tier-caps feature.
    "adv_tier_reject",
}


def emit_entry_decision(
    cfg: dict,
    *,
    link_id: str,
    entry: "Entry",
    state: State,
    slot_index: int,
    slate_size: int,
    running_gross_at_entry: float,
    binding_cap: str,
    target_dollars: float,
    adv_cap_dollars: float | None,
    intraday_confirmation_passed: bool | None,
    decision: str = "accepted",
    reason: str = "accepted",
    entry_trigger: str = "session_open",
    candidate_rank: int | None = None,
    quote: dict[str, Any] | None = None,
    shadow_controls: dict[str, bool] | None = None,
) -> None:
    """At submit time: capture every variable the analyst would want
    to know about why we picked this name at this moment.

    Phase 1.4 extension — ``decision`` / ``reason`` / ``entry_trigger``
    / ``candidate_rank`` make this the universal sink: every candidate
    considered emits exactly one record (accepted or rejected). The
    ``quote`` field is populated for confirmation-time rejections so
    analysts can study why a candidate failed.
    """
    cand = entry.candidate
    feats = dict(cand.features or {})
    gates_cfg = cfg.get("signal_gates", {}) or {}
    spec = [
        ("rvol_min", "rvol"),
        ("atr_pct_min", "atr_pct"),
        ("range_expansion_min", "range_expansion"),
        ("close_location_min", "close_location"),
        ("ema_distance_min", "ema_distance"),
        ("ema_slope_min", "ema_slope"),
    ]
    gates_breakdown = {}
    for cfg_key, feat_key in spec:
        thr = gates_cfg.get(cfg_key)
        val = feats.get(feat_key)
        gates_breakdown[feat_key] = {
            "value": _safe_float(val),
            "threshold": _safe_float(thr) if thr is not None else None,
            "passed": (
                True if thr is None
                else (val is not None and float(val) >= float(thr))
            ),
        }

    sizing_cfg = cfg.get("sizing", {}) or {}
    risk_cfg = cfg.get("risk", {}) or {}
    exits_cfg = cfg.get("exits", {}) or {}
    entry_cfg = cfg.get("entry", {}) or {}

    rec = {
        "record_type": "entry_decision",
        "ts": _now_utc_iso(),
        "ticker": entry.ticker,
        "link_id": link_id,
        "venue_code": entry.venue_code,
        "exchange": cand.exchange,
        # Phase 1.4 universal coverage.
        "decision": decision,
        "reason": reason,
        "entry_trigger": entry_trigger,
        "candidate_rank": candidate_rank,
        "candidate": {
            "close": entry.close_price,
            "signal_strength": cand.signal_strength,
            "features": feats,
        },
        "gates": gates_breakdown,
        "selection": {
            "slot_index": slot_index,
            "slate_size": slate_size,
            "max_concurrent_positions": int(sizing_cfg.get("max_concurrent_positions") or 0),
            "running_gross_at_entry": running_gross_at_entry,
            "max_gross_exposure_pct": _safe_float(risk_cfg.get("max_gross_exposure_pct")),
            "max_gross_exposure_dollars": _safe_float(risk_cfg.get("max_gross_exposure_dollars")),
        },
        "sizing": {
            "qty": entry.qty,
            "candidate_close": entry.close_price,
            "notional_at_close": entry.qty * entry.close_price,
            "equity_at_entry": _safe_float(entry.equity_at_entry),
            "per_trade_pct": _safe_float(sizing_cfg.get("per_trade_pct")),
            "max_per_trade_dollars": _safe_float(risk_cfg.get("max_per_trade_dollars")),
            "max_position_as_adv_frac": _safe_float(risk_cfg.get("max_position_as_adv_frac")),
            "avg_dollar_volume": _safe_float(feats.get("avg_dollar_volume")),
            "adv_cap_dollars": _safe_float(adv_cap_dollars),
            "target_dollars": _safe_float(target_dollars),
            "binding_cap": binding_cap,
        },
        "bracket": {
            "mode": entry_cfg.get("bracket_pricing_mode") or "actual_fill",
            "target_pct": _safe_float(exits_cfg.get("target_pct")),
            "stop_pct": _safe_float(exits_cfg.get("stop_pct")),
            "max_hold_days": int(exits_cfg.get("max_hold_days") or 0),
            "signal_fade_enabled": bool(exits_cfg.get("signal_fade_enabled", True)),
        },
        "risk": {
            "daily_loss_pct": _safe_float(risk_cfg.get("daily_loss_pct")),
            "daily_pnl_baseline_equity": _safe_float(state.get("daily_pnl_baseline_equity")),
            "daily_pnl_tripped": bool(state.get("daily_pnl_tripped", False)),
            "block_new_entries_today": bool(state.get("block_new_entries_today", False)),
            "new_entries_blocked_reason": state.get("new_entries_blocked_reason"),
        },
        "intraday_confirmation": {
            "enabled": bool((entry_cfg.get("intraday_confirmation") or {}).get("enabled")),
            "passed": intraday_confirmation_passed,
        },
        "quote": quote,
        "config_hash": config_hash(cfg),
    }
    if shadow_controls is not None:
        rec["shadow_controls"] = shadow_controls
    _append_trade_log(cfg, link_id, rec)
    # Phase 1.5: mirror to the canonical ledger so reject-path
    # analytics (Phase 7) can see every candidate considered.
    emit_ledger_event(
        cfg, event_type="entry_decision", trade_id=link_id, ticker=entry.ticker,
        payload=rec,
    )


def emit_entry_decision_rejected(
    cfg: dict | None,
    *,
    candidate: "Candidate",
    state: State,
    decision: str = "rejected",
    reason: str,
    entry_trigger: str = "session_open",
    candidate_rank: int | None,
    qty: int | None = None,
    venue_code: str | None = None,
    quote: dict[str, Any] | None = None,
    shadow_controls: dict[str, bool] | None = None,
) -> None:
    """Phase 1.4: lightweight rejected-path emission used by
    :func:`select_entries` and :func:`filter_by_intraday_confirmation`
    when there is no resolved Entry object yet (or the rejection
    happened on the entry pre-sizing). Emits the same record_type as
    the accepted path with the documented universal fields plus
    whatever context is available.

    No link_id is generated for rejected candidates — keyed only by
    ``ticker`` + ``candidate_rank`` + ``ts``. The per-trade jsonl
    is NOT written for rejections (the file name is link_id-derived,
    and rejected candidates never get one); the ledger is the
    canonical sink for these.
    """
    if cfg is None:
        return
    feats = dict(candidate.features or {})
    sizing_cfg = cfg.get("sizing", {}) or {}
    risk_cfg = cfg.get("risk", {}) or {}
    rec = {
        "record_type": "entry_decision",
        "ts": _now_utc_iso(),
        "ticker": candidate.ticker,
        "link_id": None,
        "venue_code": venue_code or candidate.venue_code,
        "exchange": candidate.exchange,
        "decision": decision,
        "reason": reason,
        "entry_trigger": entry_trigger,
        "candidate_rank": candidate_rank,
        "candidate": {
            "close": candidate.close,
            "signal_strength": candidate.signal_strength,
            "features": feats,
        },
        "sizing": {
            "qty": qty,
            "candidate_close": candidate.close,
            "per_trade_pct": _safe_float(sizing_cfg.get("per_trade_pct")),
            "max_per_trade_dollars": _safe_float(risk_cfg.get("max_per_trade_dollars")),
            "max_position_as_adv_frac": _safe_float(risk_cfg.get("max_position_as_adv_frac")),
            "avg_dollar_volume": _safe_float(feats.get("avg_dollar_volume")),
        },
        "risk": {
            "daily_pnl_tripped": bool(state.get("daily_pnl_tripped", False)),
            "block_new_entries_today": bool(state.get("block_new_entries_today", False)),
            "new_entries_blocked_reason": state.get("new_entries_blocked_reason"),
        },
        "quote": quote,
        "config_hash": config_hash(cfg),
    }
    if shadow_controls is not None:
        rec["shadow_controls"] = shadow_controls
    # No link_id — rejected events go to the ledger only.
    emit_ledger_event(
        cfg, event_type="entry_decision",
        trade_id=None, ticker=candidate.ticker,
        payload=rec,
    )


def emit_parent_submitted(
    cfg: dict, *, link_id: str, ticker: str, parent_id: str,
    qty: int, venue_code: str, http_status: int,
) -> None:
    _append_trade_log(cfg, link_id, {
        "record_type": "parent_submitted",
        "ts": _now_utc_iso(),
        "ticker": ticker, "link_id": link_id,
        "parent_order_id": parent_id,
        "qty": qty, "venue_code": venue_code,
        "http_status": http_status,
    })
    # Phase 1.5: canonical ledger event.
    emit_ledger_event(
        cfg, event_type="order_submitted", trade_id=link_id, ticker=ticker,
        role="parent",
        payload={
            "parent_order_id": parent_id, "qty": qty,
            "venue_code": venue_code, "http_status": http_status,
        },
    )


def emit_entry_fill(
    cfg: dict, *, pos: dict[str, Any], ev: "FillEvent",
) -> None:
    link_id = pos.get("link_id") or ""
    candidate_close = _safe_float(pos.get("candidate_close"))
    fill_price = _safe_float(ev.filled_avg_price)
    slippage_pct = (
        (fill_price - candidate_close) / candidate_close
        if (fill_price is not None and candidate_close and candidate_close > 0)
        else None
    )
    submitted_at = pos.get("entry_timestamp")
    fill_latency_s = None
    if submitted_at:
        try:
            sub_dt = datetime.fromisoformat(submitted_at.replace("Z", "+00:00"))
            fill_latency_s = (datetime.now(timezone.utc) - sub_dt).total_seconds()
        except Exception:
            pass
    _append_trade_log(cfg, link_id, {
        "record_type": "entry_fill",
        "ts": _now_utc_iso(),
        "ticker": ev.ticker, "link_id": link_id,
        "parent_order_id": ev.order_id,
        "filled_qty": ev.filled_qty,
        "filled_avg_price": fill_price,
        "candidate_close": candidate_close,
        "slippage_vs_candidate_close_pct": slippage_pct,
        "fill_latency_seconds": fill_latency_s,
        "partial_fill": (
            ev.filled_qty > 0 and ev.filled_qty < int(pos.get("qty") or 0)
        ),
    })
    # Phase 1.5: canonical ledger event for the parent fill.
    emit_ledger_event(
        cfg, event_type="order_fill", trade_id=link_id, ticker=ev.ticker,
        role="parent",
        payload={
            "parent_order_id": ev.order_id,
            "filled_qty": ev.filled_qty,
            "filled_avg_price": fill_price,
            "candidate_close": candidate_close,
            "slippage_vs_candidate_close_pct": slippage_pct,
            "fill_latency_seconds": fill_latency_s,
            "partial_fill": (
                ev.filled_qty > 0 and ev.filled_qty < int(pos.get("qty") or 0)
            ),
        },
    )


def emit_bracket_attached(
    cfg: dict, *, pos: dict[str, Any], target_id: str, stop_id: str,
    target_price: float, stop_price: float,
) -> None:
    link_id = pos.get("link_id") or ""
    fill_price = _safe_float(pos.get("entry_price"))
    ticker_guess = link_id.split("-")[1] if "-" in link_id else "?"
    _append_trade_log(cfg, link_id, {
        "record_type": "bracket_attached",
        "ts": _now_utc_iso(),
        "ticker": ticker_guess,
        "link_id": link_id,
        "target_order_id": target_id, "stop_order_id": stop_id,
        "target_price": target_price, "stop_price": stop_price,
        "fill_price": fill_price,
        "target_pct": _safe_float(pos.get("target_pct")),
        "stop_pct": _safe_float(pos.get("stop_pct")),
        "computed_target_check": (
            round(fill_price * (1 + float(pos.get("target_pct"))), 2)
            if fill_price is not None and pos.get("target_pct") is not None
            else None
        ),
        "computed_stop_check": (
            round(fill_price * (1 - float(pos.get("stop_pct"))), 2)
            if fill_price is not None and pos.get("stop_pct") is not None
            else None
        ),
    })
    # Phase 1.5: emit one ledger event per OCO leg so reports can
    # split the bracket pair by role.
    emit_ledger_event(
        cfg, event_type="order_submitted", trade_id=link_id, ticker=ticker_guess,
        role="target",
        payload={
            "order_id": target_id, "price": target_price,
            "fill_price": fill_price,
            "target_pct": _safe_float(pos.get("target_pct")),
        },
    )
    emit_ledger_event(
        cfg, event_type="order_submitted", trade_id=link_id, ticker=ticker_guess,
        role="stop",
        payload={
            "order_id": stop_id, "price": stop_price,
            "fill_price": fill_price,
            "stop_pct": _safe_float(pos.get("stop_pct")),
        },
    )


def emit_order_event(
    cfg: dict, *, pos: dict[str, Any], role: str, ev: "FillEvent",
) -> None:
    """Non-terminal order events (child fills don't go here when they
    cause closure; the closure record covers those). Use this for
    intermediate state changes the analyst might want to inspect."""
    link_id = pos.get("link_id") or ""
    _append_trade_log(cfg, link_id, {
        "record_type": "order_event",
        "ts": _now_utc_iso(),
        "ticker": ev.ticker, "link_id": link_id,
        "role": role,
        "order_id": ev.order_id,
        "status": ev.status,
        "filled_qty": ev.filled_qty,
        "filled_avg_price": _safe_float(ev.filled_avg_price),
    })


def emit_intraday_tick(
    cfg: dict, *, pos: dict[str, Any], ticker: str,
    quote: dict[str, Any], now_utc: datetime,
    session_end_utc: datetime | None = None,
) -> None:
    """One snapshot per minute per held position. Captures the quote
    state, the position's running P&L + excursion, distance to
    target/stop, and time-in-trade indicators."""
    link_id = pos.get("link_id") or ""
    bid = _safe_float(quote.get("bid"))
    ask = _safe_float(quote.get("ask"))
    last = _safe_float(quote.get("last"))
    bid_size = _safe_float(quote.get("bid_size"))
    ask_size = _safe_float(quote.get("ask_size"))
    mid = (bid + ask) / 2.0 if (bid and ask and ask > bid) else None
    spread = (ask - bid) if (bid and ask) else None
    spread_pct = (spread / mid) if (spread is not None and mid and mid > 0) else None

    metadata = quote.get("metadata") or {}
    day_open = _safe_float(metadata.get("open"))
    day_high = _safe_float(metadata.get("high"))
    day_low = _safe_float(metadata.get("low"))
    day_close = _safe_float(metadata.get("close"))
    day_volume = _safe_float(metadata.get("volume"))
    prev_close = _safe_float(metadata.get("prev_close"))

    entry_price = _safe_float(pos.get("entry_price"))
    qty = int(pos.get("qty") or 0)
    target_price = _safe_float(pos.get("target_price"))
    stop_price = _safe_float(pos.get("stop_price"))
    # Use mid for P&L calc; fall back to last when only one side has a quote.
    mark = mid if mid is not None else last
    unrealized_pnl = (
        (mark - entry_price) * qty
        if (mark is not None and entry_price is not None) else None
    )
    unrealized_pnl_pct = (
        (mark - entry_price) / entry_price
        if (mark is not None and entry_price is not None and entry_price > 0)
        else None
    )

    # Update peak/trough on the live mark — finer-grained than the
    # daily mark. The daily_mark function still updates from day's
    # high/low at session end so the offline analyst can cross-check.
    prev_peak = _safe_float(pos.get("peak_since_entry")) or entry_price
    prev_trough = _safe_float(pos.get("trough_since_entry")) or entry_price
    new_peak = max(prev_peak, mark) if (prev_peak is not None and mark is not None) else (prev_peak or mark)
    new_trough = min(prev_trough, mark) if (prev_trough is not None and mark is not None) else (prev_trough or mark)
    if new_peak is not None:
        pos["peak_since_entry"] = new_peak
    if new_trough is not None:
        pos["trough_since_entry"] = new_trough
    mfe_dollar = (
        (new_peak - entry_price) * qty
        if (new_peak is not None and entry_price is not None) else None
    )
    mae_dollar = (
        (new_trough - entry_price) * qty
        if (new_trough is not None and entry_price is not None) else None
    )
    drawdown_from_peak_pct = (
        (mark - new_peak) / new_peak
        if (mark is not None and new_peak and new_peak > 0)
        else None
    )
    runup_from_trough_pct = (
        (mark - new_trough) / new_trough
        if (mark is not None and new_trough and new_trough > 0)
        else None
    )

    distance_to_target_pct = (
        (target_price - mark) / mark
        if (target_price is not None and mark and mark > 0)
        else None
    )
    distance_to_stop_pct = (
        (stop_price - mark) / mark
        if (stop_price is not None and mark and mark > 0)
        else None
    )
    target_to_stop_ratio = (
        (distance_to_target_pct / abs(distance_to_stop_pct))
        if (distance_to_target_pct is not None
            and distance_to_stop_pct not in (None, 0))
        else None
    )

    # Time-in-trade.
    entry_iso = pos.get("entry_timestamp")
    minutes_held = None
    if entry_iso:
        try:
            sub_dt = datetime.fromisoformat(entry_iso.replace("Z", "+00:00"))
            minutes_held = int((now_utc - sub_dt).total_seconds() / 60)
        except Exception:
            pass
    session_minutes_remaining = None
    if session_end_utc is not None:
        session_minutes_remaining = int(
            max(0, (session_end_utc - now_utc).total_seconds() / 60)
        )

    rec = {
        "record_type": "intraday_tick",
        "ts": _now_utc_iso(),
        "ticker": ticker,
        "link_id": link_id,
        "quote": {
            "bid": bid, "ask": ask, "mid": mid,
            "spread": spread, "spread_pct": spread_pct,
            "bid_size": bid_size, "ask_size": ask_size,
            "last": last,
            "ts": quote.get("timestamp"),
        },
        "session_bar": {
            "open": day_open, "high": day_high, "low": day_low,
            "close": day_close, "volume": day_volume,
            "prev_close": prev_close,
            "gap_from_prev_close_pct": (
                (day_open - prev_close) / prev_close
                if (day_open is not None and prev_close and prev_close > 0)
                else None
            ),
            "intraday_range_pct": (
                (day_high - day_low) / day_open
                if (day_high is not None and day_low is not None
                    and day_open and day_open > 0)
                else None
            ),
        },
        "position": {
            "qty": qty,
            "entry_price": entry_price,
            "mark": mark,
            "current_value": (mark * qty) if (mark is not None) else None,
            "unrealized_pnl": unrealized_pnl,
            "unrealized_pnl_pct": unrealized_pnl_pct,
            "target_price": target_price,
            "stop_price": stop_price,
        },
        "excursion": {
            "peak_since_entry": new_peak,
            "trough_since_entry": new_trough,
            "mfe_dollar": mfe_dollar,
            "mae_dollar": mae_dollar,
            "drawdown_from_peak_pct": drawdown_from_peak_pct,
            "runup_from_trough_pct": runup_from_trough_pct,
        },
        "distance": {
            "to_target_pct": distance_to_target_pct,
            "to_stop_pct": distance_to_stop_pct,
            "target_to_stop_ratio": target_to_stop_ratio,
        },
        "time": {
            "minutes_held": minutes_held,
            "session_minutes_remaining": session_minutes_remaining,
            "entry_timestamp": entry_iso,
        },
    }

    # Phase 7.4 — shadow stop-manager. When the stop_manager is
    # disabled the runtime still computes what its rules would have
    # done at this tick. Embedded in every intraday_tick record so a
    # downstream study can ablate the rules without rerunning.
    try:
        sm_cfg = ((cfg.get("exits") or {}).get("stop_manager") or {})
        # The function honors its own enabled flag; we explicitly call
        # the rule body even when disabled by temporarily forcing the
        # enabled flag to True via a shadow copy.
        if not sm_cfg.get("enabled"):
            shadow_cfg = dict(cfg)
            shadow_exits = dict(cfg.get("exits") or {})
            shadow_sm = dict(sm_cfg)
            shadow_sm["enabled"] = True
            shadow_exits["stop_manager"] = shadow_sm
            shadow_cfg["exits"] = shadow_exits
            shadow_target_stop = desired_stop_from_mfe(pos, shadow_cfg)
        else:
            shadow_target_stop = desired_stop_from_mfe(pos, cfg)
        rule_triggered = None
        for rule in sm_cfg.get("rules") or []:
            if (entry_price is not None
                    and new_peak is not None
                    and entry_price > 0):
                mfe = (new_peak - entry_price) / entry_price
                if mfe >= float(rule.get("mfe_min") or 0):
                    rule_triggered = (
                        f"mfe_{int(float(rule.get('mfe_min') or 0) * 100)}pct"
                    )
        would_have_moved = bool(
            shadow_target_stop is not None
            and stop_price is not None
            and shadow_target_stop > stop_price
        )
        would_have_stopped_out = bool(
            shadow_target_stop is not None
            and mark is not None
            and mark <= shadow_target_stop
        )
        rec["shadow_stop_manager"] = {
            "would_have_moved_stop": would_have_moved,
            "shadow_stop_price": shadow_target_stop,
            "rule_triggered": rule_triggered,
            "would_have_stopped_out": would_have_stopped_out,
        }
    except Exception as e:
        LOG.debug("shadow_stop_manager compute failed: %s", e)

    _append_trade_log(cfg, link_id, rec)


def emit_exit(
    cfg: dict, *, pos: dict[str, Any], closure_record: dict[str, Any],
) -> None:
    """Closure twin to the daily_summary closure record. Carries the
    entry_decision-equivalent context plus everything the analyst
    needs about the exit (slippage, hold duration, MFE/MAE)."""
    link_id = pos.get("link_id") or ""
    rec = dict(closure_record)
    rec["record_type"] = "exit"
    rec["ts"] = rec.get("exit_timestamp") or _now_utc_iso()
    _append_trade_log(cfg, link_id, rec)


# ---- intraday tick loop


def _fetch_quotes_batch(
    instruments: list[tuple[str, str]],
    http: httpx.Client,
    api_key: str,
) -> dict[str, dict[str, Any]]:
    """POST /api/v2/quotes with multiple instruments. Returns a dict
    keyed by canonical_symbol. Empty / failure → empty dict (caller
    skips the tick log for missing tickers)."""
    if not instruments:
        return {}
    body = {
        "apikey": api_key,
        "instruments": [
            {"venue_code": v, "canonical_symbol": s} for s, v in instruments
        ],
    }
    try:
        r = http.post("/api/v2/quotes", json=body, headers=_api_headers(api_key))
    except httpx.HTTPError as e:
        LOG.warning("intraday quote batch fetch failed: %s", e)
        return {}
    if r.status_code != 200:
        LOG.warning(
            "intraday quote batch HTTP %d: %s",
            r.status_code, (r.text or "")[:200],
        )
        return {}
    try:
        rows = r.json().get("data") or []
    except ValueError:
        return {}
    out: dict[str, dict[str, Any]] = {}
    for row in rows:
        sym = (row or {}).get("instrument", {}).get("canonical_symbol")
        q = (row or {}).get("quote") or {}
        if sym:
            out[sym] = q
    return out


def run_intraday_tick_logging(
    cfg: dict,
    state: State,
    http: httpx.Client,
    api_key: str,
    *,
    state_path: Path,
    now_utc: datetime,
    interval_seconds: int = 60,
) -> list[str]:
    """Once per main-loop tick: log a per-position quote snapshot if
    at least ``interval_seconds`` have elapsed since that position's
    last tick. Mutates pos.last_tick_logged_at + pos.peak/trough_since
    in place. Returns the list of tickers logged this call."""
    open_positions = state.get("open_positions") or {}
    due: list[tuple[str, str]] = []  # (symbol, venue)
    for ticker, pos in open_positions.items():
        if pos.get("status") != "filled":
            continue
        last_iso = pos.get("last_tick_logged_at")
        if last_iso:
            try:
                last_dt = datetime.fromisoformat(last_iso.replace("Z", "+00:00"))
                if (now_utc - last_dt).total_seconds() < interval_seconds:
                    continue
            except Exception:
                pass
        due.append((
            ticker,
            pos.get("venue_code") or cfg["sizing"]["default_venue_code"],
        ))
    if not due:
        return []

    quotes = _fetch_quotes_batch(due, http, api_key)
    if not quotes:
        return []

    logged: list[str] = []
    # Compute today's session-end UTC for "minutes remaining" — used
    # in the tick payload. Falls back to None when the cfg session
    # block isn't loadable.
    session_end_utc: datetime | None = None
    try:
        import pytz
        session_end_str = (cfg.get("session") or {}).get("end") or "15:55"
        h, m = (int(p) for p in session_end_str.split(":")[:2])
        et = pytz.timezone((cfg.get("session") or {}).get("timezone") or "America/New_York")
        today_et = _to_eastern(now_utc).date()
        session_end_utc = et.localize(
            datetime.combine(today_et, _dtime(h, m))
        ).astimezone(timezone.utc)
    except Exception:
        session_end_utc = None

    dirty = False
    for ticker, _venue in due:
        q = quotes.get(ticker)
        if q is None:
            continue
        pos = open_positions.get(ticker)
        if pos is None:
            continue
        try:
            emit_intraday_tick(
                cfg, pos=pos, ticker=ticker, quote=q,
                now_utc=now_utc, session_end_utc=session_end_utc,
            )
            pos["last_tick_logged_at"] = now_utc.isoformat()
            dirty = True
            logged.append(ticker)
        except Exception as e:
            LOG.warning("emit_intraday_tick failed for %s: %s", ticker, e)
    if dirty:
        save_state(state, state_path)
    return logged


# ---------------------------------------------------------------- Phase 7.1 — liquidity monitor


def _classify_liquidity_status(
    quote: dict[str, Any] | None, cfg_lm: dict, now_utc: datetime,
) -> tuple[str, dict[str, Any]]:
    """Phase 7.3 helper. Return ``(status, metrics)``.

    Status ladder (most-severe wins):
      * ``stale``   — quote age >= severe_stale_quote_seconds
      * ``severe``  — spread_pct >= spread_severe_pct
      * ``warning`` — spread_pct >= spread_warning_pct OR age >=
                       stale_quote_seconds
      * ``ok``      — none of the above

    ``metrics`` carries the raw spread_pct / quote_age_seconds / mid
    values for downstream telemetry.
    """
    if quote is None:
        return "stale", {"reason": "no_quote"}
    try:
        bid = float(quote.get("bid") or 0)
        ask = float(quote.get("ask") or 0)
    except (TypeError, ValueError):
        return "stale", {"reason": "bad_quote"}
    if bid <= 0 or ask <= 0 or ask <= bid:
        return "stale", {"reason": "bad_quote"}
    mid = (bid + ask) / 2.0
    spread_pct = (ask - bid) / mid

    quote_age_seconds: float | None = None
    ts = quote.get("timestamp")
    if isinstance(ts, str):
        quote_age_seconds = seconds_since_iso(ts, now_utc=now_utc)
    severe_stale = float(cfg_lm.get("severe_stale_quote_seconds") or 60)
    warning_stale = float(cfg_lm.get("stale_quote_seconds") or 30)
    severe_spread = float(cfg_lm.get("spread_severe_pct") or 0.05)
    warning_spread = float(cfg_lm.get("spread_warning_pct") or 0.03)

    if quote_age_seconds is not None and quote_age_seconds >= severe_stale:
        return "stale", {
            "spread_pct": spread_pct, "mid": mid,
            "quote_age_seconds": quote_age_seconds,
        }
    if spread_pct >= severe_spread:
        return "severe", {
            "spread_pct": spread_pct, "mid": mid,
            "quote_age_seconds": quote_age_seconds,
        }
    if (
        spread_pct >= warning_spread
        or (quote_age_seconds is not None and quote_age_seconds >= warning_stale)
    ):
        return "warning", {
            "spread_pct": spread_pct, "mid": mid,
            "quote_age_seconds": quote_age_seconds,
        }
    return "ok", {
        "spread_pct": spread_pct, "mid": mid,
        "quote_age_seconds": quote_age_seconds,
    }


def run_liquidity_monitor_pass(
    cfg: dict,
    state: State,
    http: httpx.Client | None,
    api_key: str | None,
    *,
    state_path: Path,
    now_utc: datetime | None = None,
) -> list[str]:
    """Phase 7.3 — per-position liquidity classifier.

    Returns the list of tickers for which a liquidity_status event
    was emitted this call. No-op when ``cfg.liquidity_monitor.
    enabled`` is False.

    Position fields updated in place (Phase 7.2):
      * ``liquidity_warning_count`` / ``liquidity_severe_count`` —
        cumulative counters for the session.
      * ``last_liquidity_status`` — current bucket.
      * ``max_spread_pct_seen`` / ``max_quote_age_seconds_seen`` —
        running maxima for the position's life.

    When ``action_on_severe_if_profitable`` is non-``none`` AND the
    position is profitable AND the severe count crosses the
    threshold, raise NotImplementedError to signal that the
    operator-selected action is scaffolded but not yet wired.
    Calling code catches this with the standard try/except
    (LOG.exception) so the strategy keeps ticking.
    """
    lm_cfg = cfg.get("liquidity_monitor") or {}
    if not lm_cfg.get("enabled"):
        return []
    now = now_utc or datetime.now(timezone.utc)
    open_positions = state.get("open_positions") or {}
    if not open_positions or http is None or api_key is None:
        return []
    interval_s = float(lm_cfg.get("tick_interval_seconds") or 30)
    due: list[tuple[str, str]] = []
    for ticker, pos in open_positions.items():
        if pos.get("status") != "filled":
            continue
        last = pos.get("last_liquidity_check_at")
        if last:
            try:
                last_dt = datetime.fromisoformat(last.replace("Z", "+00:00"))
                if last_dt.tzinfo is None:
                    last_dt = last_dt.replace(tzinfo=timezone.utc)
                if (now - last_dt).total_seconds() < interval_s:
                    continue
            except Exception:
                pass
        due.append((
            ticker,
            pos.get("venue_code") or cfg["sizing"]["default_venue_code"],
        ))
    if not due:
        return []
    quotes = _fetch_quotes_batch(due, http, api_key)
    if not quotes:
        return []
    consecutive_n = int(lm_cfg.get("consecutive_warning_ticks") or 3)
    action_cfg = (lm_cfg.get("action_on_severe_if_profitable") or "none").lower()
    emitted: list[str] = []
    dirty = False
    for ticker, _venue in due:
        pos = open_positions.get(ticker)
        if pos is None:
            continue
        q = quotes.get(ticker)
        status, metrics = _classify_liquidity_status(q, lm_cfg, now)
        pos["last_liquidity_check_at"] = now.isoformat()
        pos["last_liquidity_status"] = status
        # Cumulative counters.
        if status == "warning":
            pos["liquidity_warning_count"] = int(
                pos.get("liquidity_warning_count", 0)
            ) + 1
        elif status == "severe":
            pos["liquidity_severe_count"] = int(
                pos.get("liquidity_severe_count", 0)
            ) + 1
        # Running maxima.
        sp = metrics.get("spread_pct")
        if sp is not None:
            prev_max = float(pos.get("max_spread_pct_seen") or 0)
            if sp > prev_max:
                pos["max_spread_pct_seen"] = sp
        age = metrics.get("quote_age_seconds")
        if age is not None:
            prev_max_age = float(pos.get("max_quote_age_seconds_seen") or 0)
            if age > prev_max_age:
                pos["max_quote_age_seconds_seen"] = age
        # Telemetry record.
        rec = {
            "record_type": "liquidity_status",
            "ts": _now_utc_iso(),
            "ticker": ticker,
            "link_id": pos.get("link_id"),
            "status": status,
            **metrics,
            "warning_count": pos.get("liquidity_warning_count", 0),
            "severe_count": pos.get("liquidity_severe_count", 0),
        }
        _append_trade_log(cfg, pos.get("link_id"), rec)
        emit_ledger_event(
            cfg, event_type="liquidity_status",
            trade_id=pos.get("link_id"), ticker=ticker,
            payload=rec,
        )
        emitted.append(ticker)
        dirty = True

        # Optional action wiring.
        if action_cfg != "none" and status == "severe":
            severe_n = int(pos.get("liquidity_severe_count", 0))
            entry_price = pos.get("entry_price")
            mid = metrics.get("mid")
            is_profitable = (
                entry_price is not None and mid is not None
                and float(mid) > float(entry_price)
            )
            if is_profitable and severe_n >= consecutive_n and not pos.get(
                "liquidity_action_taken"
            ):
                pos["liquidity_action_taken"] = True
                if action_cfg in {"tighten_stop", "exit_partial"}:
                    # Scaffolded but not yet wired — Phase 5's
                    # stop-manager is the natural home for tighten_
                    # stop; exit_partial needs a partial-order
                    # path the strategy doesn't yet have.
                    raise NotImplementedError(
                        f"liquidity_monitor.action_on_severe_if_profitable={action_cfg!r} "
                        "is scaffolded but not yet wired. Set to 'none' until follow-up."
                    )
    if dirty:
        save_state(state, state_path)
    return emitted


def close_position(
    ticker: str,
    state: State,
    cfg: dict,
    *,
    state_path: Path,
    summary_path: Path,
    exit_price: float,
    reason: str,
) -> dict[str, Any]:
    """Compute realized PnL, append jsonl, drop from state.

    The closure record carries the analytic-enrichment fields the
    operator uses to tune target_pct / stop_pct / max_hold_days /
    signal_gates: hold duration, max-favorable / max-adverse
    excursion, peak / trough since entry, plus the entry features.
    """
    pos = (state.get("open_positions") or {}).get(ticker)
    if pos is None:
        return {}
    entry_price = float(pos.get("entry_price") or 0.0)
    qty = int(pos.get("qty") or 0)
    realized = (exit_price - entry_price) * qty
    entry_iso = pos.get("entry_timestamp")
    exit_iso = datetime.now(timezone.utc).isoformat()
    # Hold duration in NYSE trading days. Falls back to None when
    # entry_timestamp is missing (very old states).
    hold_trading_days: int | None = None
    if entry_iso:
        try:
            today_et = _to_eastern(datetime.now(timezone.utc)).date()
            hold_trading_days = trading_days_since(entry_iso, today_et)
        except Exception:
            hold_trading_days = None
    entry_to_exit_pct = (
        (exit_price - entry_price) / entry_price
        if entry_price > 0 else None
    )
    peak = pos.get("peak_since_entry")
    trough = pos.get("trough_since_entry")
    try:
        peak_f = float(peak) if peak is not None else None
        trough_f = float(trough) if trough is not None else None
    except (TypeError, ValueError):
        peak_f = trough_f = None
    mfe_dollar = (peak_f - entry_price) * qty if (peak_f is not None and entry_price > 0) else None
    mae_dollar = (trough_f - entry_price) * qty if (trough_f is not None and entry_price > 0) else None
    mfe_pct = (peak_f - entry_price) / entry_price if (peak_f is not None and entry_price > 0) else None
    mae_pct = (trough_f - entry_price) / entry_price if (trough_f is not None and entry_price > 0) else None

    record = {
        "record_type": "closure",
        "ticker": ticker,
        "qty": qty,
        "entry_price": entry_price,
        "exit_price": exit_price,
        "entry_timestamp": entry_iso,
        "exit_timestamp": exit_iso,
        "realized_pnl": realized,
        "reason": reason,
        "entry_features": pos.get("entry_features", {}),
        "venue_code": pos.get("venue_code"),
        "exchange": pos.get("exchange"),
        "signal_strength": pos.get("signal_strength"),
        "candidate_close": pos.get("candidate_close"),
        "target_pct": pos.get("target_pct"),
        "stop_pct": pos.get("stop_pct"),
        "target_price": pos.get("target_price"),
        "stop_price": pos.get("stop_price"),
        "bracket_pricing_mode": pos.get("bracket_pricing_mode"),
        "hold_trading_days": hold_trading_days,
        "entry_to_exit_pct": entry_to_exit_pct,
        "peak_since_entry": peak_f,
        "trough_since_entry": trough_f,
        "mfe_dollar": mfe_dollar,
        "mae_dollar": mae_dollar,
        "mfe_pct": mfe_pct,
        "mae_pct": mae_pct,
        "link_id": pos.get("link_id"),
        "entry_trigger": pos.get("entry_trigger") or "session_open",
    }
    append_closure_record(summary_path, record)
    # Per-trade rich log: write the exit record under the same
    # link_id BEFORE we drop pos from state.
    emit_exit(cfg, pos=pos, closure_record=record)
    # Phase 1.5: canonical ledger event. The closure carries the
    # full record so recompute_daily_summary_from_ledger can rebuild
    # the daily summary from this stream alone.
    #
    # R-multiple. Phase 6.5: prefer the position's recorded
    # planned_risk_dollars (set at sizing time — equals target_risk_
    # dollars for risk_per_trade mode, entry*stop_pct*qty for
    # equal_slice mode). Fall back to the Phase 1 stop_pct
    # computation for legacy positions that lack the field.
    planned_risk = pos.get("planned_risk_dollars")
    if planned_risk is None:
        stop_pct_v = pos.get("stop_pct")
        try:
            if stop_pct_v is not None and entry_price > 0 and qty:
                planned_risk = abs(float(entry_price) * float(stop_pct_v) * float(qty))
        except Exception:
            planned_risk = None
    r_multiple = None
    try:
        if planned_risk is not None and float(planned_risk) > 0:
            r_multiple = realized / float(planned_risk)
    except Exception:
        r_multiple = None
    # session_date for the ledger uses the exit's ET-local date, NOT
    # the entry date — closure_event aggregations are keyed on the
    # day the realized pnl posts.
    try:
        sess_date = _to_eastern(
            datetime.now(timezone.utc)
        ).date().isoformat()
    except Exception:
        sess_date = None
    ledger_payload = dict(record)
    ledger_payload["planned_risk_dollars"] = planned_risk
    ledger_payload["R_multiple"] = r_multiple
    emit_ledger_event(
        cfg, event_type="closure", trade_id=pos.get("link_id"), ticker=ticker,
        session_date=sess_date,
        payload=ledger_payload,
    )
    # Bankroll update happens BEFORE state["open_positions"].pop +
    # save_state so the bankroll mutation is part of the same atomic
    # write. apply_realized_pnl_to_bankroll is a no-op when the
    # feature is off.
    apply_realized_pnl_to_bankroll(state, cfg, realized)
    # Phase 3.5 — circuit-breaker counters update right after the
    # bankroll mutation so the bankroll figure used by the slice-loss
    # check is post-closure.
    try:
        update_daily_closure_risk_state(
            state, cfg, reason=reason, realized_pnl=realized,
        )
    except Exception as e:
        LOG.exception(
            "update_daily_closure_risk_state failed (continuing): %s", e,
        )
    state["open_positions"].pop(ticker, None)
    state.get("pending_signal_fade_exits", {}).pop(ticker, None)
    save_state(state, state_path)
    bk_now = (state.get("bankroll") or {}).get("current_dollars")
    LOG.info(
        "closed %s: %s pnl=%.2f hold=%s mfe=%s mae=%s%s",
        ticker, reason, realized, hold_trading_days, mfe_dollar, mae_dollar,
        f" bankroll=${bk_now:.2f}" if bk_now is not None else "",
    )
    return record


def process_fill_events_for_closures(
    events: list[FillEvent],
    state: State,
    cfg: dict,
    *,
    state_path: Path,
    summary_path: Path,
) -> list[dict[str, Any]]:
    """Map fill events to closures based on which child filled.

    - parent filled        → ``opened`` jsonl record (Item 8 #8) so
                              write_session_summary's count_opened
                              reflects today's actual entries
    - target child filled  → ``target_hit``
    - stop child filled    → ``stop_hit``
    - exit_order_id filled → use the recorded exit reason
                              (time_stop / signal_fade)
    """
    out: list[dict[str, Any]] = []
    open_positions = state.get("open_positions") or {}
    for ev in events:
        pos = open_positions.get(ev.ticker)
        if pos is None:
            continue
        if ev.role == "parent" and ev.status == "FILLED":
            # Append an opened record so the daily summary's
            # count_opened counts trades that *opened today*, not
            # "positions still open at session end". A round-trip
            # (open + close intraday) writes one opened + one closure
            # → count_opened=1, count_closed=1, both correct.
            entry_iso = (
                pos.get("entry_timestamp")
                or datetime.now(timezone.utc).isoformat()
            )
            entry_price = float(ev.filled_avg_price or 0.0)
            qty = int(pos.get("qty") or ev.filled_qty or 0)
            notional = entry_price * qty if entry_price > 0 else None
            equity_at_entry = pos.get("equity_at_entry")
            try:
                equity_at_entry = float(equity_at_entry) if equity_at_entry is not None else None
            except (TypeError, ValueError):
                equity_at_entry = None
            notional_pct_of_equity = (
                (notional / equity_at_entry)
                if (notional is not None and equity_at_entry and equity_at_entry > 0)
                else None
            )
            candidate_close = pos.get("candidate_close")
            try:
                candidate_close = float(candidate_close) if candidate_close is not None else None
            except (TypeError, ValueError):
                candidate_close = None
            gap_at_open_pct = (
                ((entry_price - candidate_close) / candidate_close)
                if (candidate_close and candidate_close > 0 and entry_price > 0)
                else None
            )
            ic_cfg = _intraday_confirmation_cfg(cfg) if "_intraday_confirmation_cfg" in globals() else {}
            try:
                append_closure_record(summary_path, {
                    "record_type": "opened",
                    "ticker": ev.ticker,
                    "qty": qty,
                    "entry_price": entry_price,
                    "entry_timestamp": entry_iso,
                    "venue_code": pos.get("venue_code"),
                    "exchange": pos.get("exchange"),
                    "entry_features": pos.get("entry_features", {}),
                    "link_id": pos.get("link_id"),
                    # --- Item-(post-9) analytic enrichment ---
                    "signal_strength": pos.get("signal_strength"),
                    "candidate_close": candidate_close,
                    "gap_at_open_pct": gap_at_open_pct,
                    "target_pct": pos.get("target_pct"),
                    "stop_pct": pos.get("stop_pct"),
                    "target_price": pos.get("target_price"),
                    "stop_price": pos.get("stop_price"),
                    "bracket_pricing_mode": pos.get("bracket_pricing_mode"),
                    "equity_at_entry": equity_at_entry,
                    "notional": notional,
                    "notional_pct_of_equity": notional_pct_of_equity,
                    "intraday_confirmation_enabled": bool(ic_cfg.get("enabled")) if ic_cfg else False,
                    "entry_trigger": pos.get("entry_trigger") or "session_open",
                })
            except Exception as e:
                LOG.exception(
                    "could not append opened record for %s: %s", ev.ticker, e,
                )
            # Don't `continue` — fall through so a parent fill that
            # also coincides with a close (rare) still gets handled
            # below. Currently no other branch matches role="parent"
            # so this is a no-op, but the structure is forgiving.
        if ev.role == "target" and ev.status in {"FILLED"}:
            price = ev.filled_avg_price or pos.get("target_price") or 0.0
            # Phase 1.5: ledger event for the target leg fill (before
            # close_position emits the closure event so the chronology
            # in the ledger reflects broker order).
            emit_ledger_event(
                cfg, event_type="order_fill",
                trade_id=pos.get("link_id"), ticker=ev.ticker, role="target",
                payload={
                    "order_id": ev.order_id, "filled_qty": ev.filled_qty,
                    "filled_avg_price": _safe_float(ev.filled_avg_price),
                },
            )
            out.append(close_position(
                ev.ticker, state, cfg,
                state_path=state_path, summary_path=summary_path,
                exit_price=float(price), reason="target_hit",
            ))
            # Phase 3.2 — gated rescreen flag.
            if should_set_rescreen_pending("target_hit", state, cfg):
                state["rescreen_pending"] = True
        elif ev.role == "stop" and ev.status in {"FILLED"}:
            price = ev.filled_avg_price or pos.get("stop_price") or 0.0
            emit_ledger_event(
                cfg, event_type="order_fill",
                trade_id=pos.get("link_id"), ticker=ev.ticker, role="stop",
                payload={
                    "order_id": ev.order_id, "filled_qty": ev.filled_qty,
                    "filled_avg_price": _safe_float(ev.filled_avg_price),
                },
            )
            out.append(close_position(
                ev.ticker, state, cfg,
                state_path=state_path, summary_path=summary_path,
                exit_price=float(price), reason="stop_hit",
            ))
            if should_set_rescreen_pending("stop_hit", state, cfg):
                state["rescreen_pending"] = True
        elif ev.role == "exit" and ev.status in {"FILLED"}:
            reason = pos.get("exit_reason") or "time_stop"
            price = ev.filled_avg_price or pos.get("exit_fill_price") or 0.0
            emit_ledger_event(
                cfg, event_type="order_fill",
                trade_id=pos.get("link_id"), ticker=ev.ticker, role="exit",
                payload={
                    "order_id": ev.order_id, "filled_qty": ev.filled_qty,
                    "filled_avg_price": _safe_float(ev.filled_avg_price),
                    "exit_reason": reason,
                },
            )
            out.append(close_position(
                ev.ticker, state, cfg,
                state_path=state_path, summary_path=summary_path,
                exit_price=float(price), reason=reason,
            ))
            # time_stop sets rescreen_pending; signal_fade does NOT
            # (it fires at 16:05 ET, past the rescreen entry cutoff,
            # and there's no productive re-entry on a signal-faded
            # name anyway).
            if reason != "signal_fade" and should_set_rescreen_pending(reason, state, cfg):
                state["rescreen_pending"] = True
    return out


# ---------------------------------------------------------------- daily P&L


def update_daily_pnl(
    state: State,
    current_equity: float,
    cfg: dict,
    *,
    state_path: Path,
) -> bool:
    """Compare current equity to the session baseline. Trip the daily
    loss circuit breaker once, log the trip ratios. Returns True if
    the trip happened on this call.

    Phase 5.1: when ``cfg.risk.daily_loss_pct`` is null (paper-mode
    profile), the trip is disabled — equity may grind down without
    blocking new entries. Shadow controls still report what would
    have been tripped under the legacy threshold."""
    baseline = state.get("daily_pnl_baseline_equity")
    if baseline in (None, 0):
        return False
    if state.get("daily_pnl_tripped"):
        return False
    raw_threshold = cfg["risk"].get("daily_loss_pct")
    if raw_threshold is None:
        # Phase 5.1: feature disabled in paper-mode profile.
        return False
    pnl_pct = (current_equity - float(baseline)) / float(baseline)
    threshold = float(raw_threshold)
    if pnl_pct <= -threshold:
        state["daily_pnl_tripped"] = True
        # Phase 3.5: mirror into the unified block flag so entry
        # gates only need to check one field. (select_entries
        # already checks both for back-compat.)
        if not state.get("block_new_entries_today"):
            state["block_new_entries_today"] = True
            state["new_entries_blocked_reason"] = "daily_pnl_tripped"
        save_state(state, state_path)
        LOG.error(
            "DAILY P&L CIRCUIT BREAKER tripped: pnl=%.4f baseline=%.2f current=%.2f threshold=-%.4f",
            pnl_pct, baseline, current_equity, threshold,
        )
        return True
    return False


# ---------------------------------------------------------------- halt detection


_HALT_STATUSES = {"held", "HELD", "pending_review", "PENDING_REVIEW"}


def _is_halt_signal(row: dict[str, Any]) -> bool:
    status = (row.get("native_status") or row.get("status") or "")
    if status in _HALT_STATUSES:
        return True
    canonical = (row.get("canonical_status") or "").upper()
    if canonical in {"HELD", "PENDING_REVIEW"}:
        return True
    reject = (row.get("reject_reason") or row.get("reject_reasons") or "").lower()
    return "halt" in reject


# ---------------------------------------------------------------- positions / orders fetch


def fetch_open_orders(http: httpx.Client, api_key: str, status="open") -> list[dict]:
    # Phase 1.1: header-only auth on GET; keep ``status`` query.
    r = http.get("/api/v2/orders",
                 headers=_api_headers(api_key),
                 params={"status": status})
    r.raise_for_status()
    return r.json().get("data", {}).get("orders", []) or []


def fetch_positions(http: httpx.Client, api_key: str) -> list[dict]:
    # Phase 1.1: header-only auth on GET (no query needed).
    r = http.get("/api/v2/positions", headers=_api_headers(api_key))
    r.raise_for_status()
    return r.json().get("data", {}).get("positions", []) or []


# ---------------------------------------------------------------- reconciliation


def _exit_fill_from_tracked_children(
    pos: dict[str, Any],
    all_orders_by_id: dict[str, dict],
) -> tuple[float, int, str] | None:
    """Find the actual exit fill for a vanished position by walking
    its tracked sell-side order IDs.

    Returns ``(filled_avg_price, filled_qty, role)`` for the first
    FILLED order found, or ``None`` if no tracked child shows a fill.

    Roles searched in order: ``target`` (OCO take-profit), ``stop``
    (OCO stop-loss), ``exit`` (standalone helper for time_stop /
    signal_fade exits via ``pos.exit_order_id``).

    Used by :func:`reconcile_at_startup` to recover real PnL when a
    position disappears between restarts — without this, OCO stops
    that fire while the strategy is offline get recorded as zero-PnL
    ``closed_externally`` stubs and daily_summary drifts from the
    broker.
    """
    children = pos.get("child_order_ids") or {}
    # Walk OCO peers first, then any standalone exit order. Preserve
    # a stable role order (target → stop → exit) so the recovered
    # reason is deterministic when multiple orders somehow show
    # ``filled`` (OCO guarantees at most one fills; defensive only).
    candidates: list[tuple[str, str]] = []
    for role in ("target", "stop"):
        oid = children.get(role)
        if oid:
            candidates.append((role, oid))
    exit_oid = pos.get("exit_order_id")
    if exit_oid:
        candidates.append(("exit", exit_oid))

    for role, oid in candidates:
        order = all_orders_by_id.get(oid)
        if not order:
            continue
        native = (order.get("native_status")
                  or order.get("canonical_status")
                  or order.get("status") or "").lower()
        if native != "filled":
            continue
        try:
            price = float(order.get("filled_avg_price") or 0.0)
        except (TypeError, ValueError):
            continue
        try:
            filled_qty = int(float(
                order.get("filled_qty")
                or order.get("filled_quantity")
                or 0
            ))
        except (TypeError, ValueError):
            filled_qty = 0
        if price > 0:
            return price, filled_qty, role
    return None


def reconcile_at_startup(
    state: State,
    http: httpx.Client,
    api_key: str,
    *,
    state_path: Path,
    summary_path: Path,
    cfg: dict | None = None,
) -> dict[str, Any]:
    """Bring state in line with broker reality. Runs once before the
    main loop. Returns a summary dict for logging.

    Item 6 fix: even when local state is empty we still fetch broker
    positions so an untracked broker position (e.g., user moved
    state.json aside, deployed a fresh checkout, or the strategy
    crashed mid-entry) surfaces as an ``untracked`` warning. Previously
    the function returned early on empty state and silently never
    looked at the broker — directly contradicting the runbook claim
    that fresh state surfaces untracked broker positions.
    """
    summary = {
        "qty_corrected": [], "closed_externally": [], "untracked": [],
        "child_status_corrected": [], "pending_signal_fade_resolved": [],
    }
    open_positions = state.get("open_positions") or {}
    pending_signal_fade = state.get("pending_signal_fade_exits") or {}

    try:
        broker_positions = fetch_positions(http, api_key)
    except Exception as e:
        LOG.exception("reconcile: positions fetch failed: %s", e)
        return summary
    try:
        broker_open_orders = fetch_open_orders(http, api_key, status="open")
        broker_all_orders = fetch_open_orders(http, api_key, status="all")
    except Exception as e:
        LOG.exception("reconcile: orders fetch failed: %s", e)
        return summary

    # Empty local state but no broker positions either → genuine
    # fresh start. Log and return after the broker check completed.
    if not open_positions and not pending_signal_fade and not broker_positions:
        LOG.info("reconciliation: empty state + no broker positions; fresh start")
        return summary

    # Position keys vary by adapter — try canonical_symbol first.
    broker_pos_by_ticker: dict[str, dict] = {}
    for p in broker_positions:
        key = p.get("canonical_symbol") or p.get("symbol") or p.get("ticker")
        if key:
            broker_pos_by_ticker[key] = p

    all_orders_by_id: dict[str, dict] = {
        (o.get("id") or o.get("order_id")): o for o in broker_all_orders
    }

    for ticker, pos in list(open_positions.items()):
        if ticker not in broker_pos_by_ticker:
            # Position vanished from the broker between restarts.
            #
            # Best-effort recovery: walk the tracked child orders
            # (target/stop OCO peers + any standalone exit order) and
            # promote the first FILLED one into the closure record.
            # Without this, an OCO stop that fires overnight produces
            # a zero-PnL ``closed_externally`` stub and daily_summary
            # drifts from broker reality by the missed loss / gain
            # (e.g. BLDP 2026-05-08: stop fired @ 4.20 vs entry 4.7618
            # — the strategy's books missed −$1,173.68 until 2026-05-11
            # when this fix landed). If no tracked child shows a fill
            # we still write the $0 stub as before so the position
            # is dropped from state.
            entry_price = float(pos.get("entry_price") or 0.0)
            qty = int(pos.get("qty") or 0)
            entry_iso = pos.get("entry_timestamp")
            exit_iso = datetime.now(timezone.utc).isoformat()

            fill = _exit_fill_from_tracked_children(pos, all_orders_by_id)
            if fill is not None:
                exit_price, _exit_qty, role = fill
                if role == "target":
                    reason = "target_hit"
                elif role == "stop":
                    reason = "stop_hit"
                else:  # role == "exit" (signal_fade / time_stop helper)
                    reason = pos.get("exit_reason") or "signal_fade"
                realized = (exit_price - entry_price) * qty
            else:
                exit_price = entry_price
                reason = "closed_externally"
                realized = 0.0

            hold_trading_days: int | None = None
            if entry_iso:
                try:
                    today_et = _to_eastern(datetime.now(timezone.utc)).date()
                    hold_trading_days = trading_days_since(entry_iso, today_et)
                except Exception:
                    hold_trading_days = None
            entry_to_exit_pct = (
                (exit_price - entry_price) / entry_price
                if entry_price > 0 else None
            )
            peak = pos.get("peak_since_entry")
            trough = pos.get("trough_since_entry")
            try:
                peak_f = float(peak) if peak is not None else None
                trough_f = float(trough) if trough is not None else None
            except (TypeError, ValueError):
                peak_f = trough_f = None
            mfe_dollar = (
                (peak_f - entry_price) * qty
                if (peak_f is not None and entry_price > 0) else None
            )
            mae_dollar = (
                (trough_f - entry_price) * qty
                if (trough_f is not None and entry_price > 0) else None
            )
            mfe_pct = (
                (peak_f - entry_price) / entry_price
                if (peak_f is not None and entry_price > 0) else None
            )
            mae_pct = (
                (trough_f - entry_price) / entry_price
                if (trough_f is not None and entry_price > 0) else None
            )

            record = {
                "record_type": "closure",
                "ticker": ticker, "qty": qty,
                "entry_price": entry_price,
                "exit_price": exit_price,
                "entry_timestamp": entry_iso,
                "exit_timestamp": exit_iso,
                "realized_pnl": realized,
                "reason": reason,
                "entry_features": pos.get("entry_features", {}),
                "venue_code": pos.get("venue_code"),
                "exchange": pos.get("exchange"),
                "signal_strength": pos.get("signal_strength"),
                "candidate_close": pos.get("candidate_close"),
                "target_pct": pos.get("target_pct"),
                "stop_pct": pos.get("stop_pct"),
                "target_price": pos.get("target_price"),
                "stop_price": pos.get("stop_price"),
                "bracket_pricing_mode": pos.get("bracket_pricing_mode"),
                "hold_trading_days": hold_trading_days,
                "entry_to_exit_pct": entry_to_exit_pct,
                "peak_since_entry": peak_f,
                "trough_since_entry": trough_f,
                "mfe_dollar": mfe_dollar,
                "mae_dollar": mae_dollar,
                "mfe_pct": mfe_pct,
                "mae_pct": mae_pct,
                "link_id": pos.get("link_id"),
                "recovered_from_child_fill": fill is not None,
            }
            append_closure_record(summary_path, record)
            # Phase 1.5: mirror the closure into the canonical ledger
            # so reconcile-recovered fills are visible alongside live
            # closures. R-multiple computed against the same planned-
            # risk basis as close_position so reports compare apples-
            # to-apples.
            _stop_pct_rec = pos.get("stop_pct")
            _planned_risk_rec = None
            _r_mult_rec = None
            try:
                if _stop_pct_rec is not None and entry_price > 0 and qty:
                    _planned_risk_rec = abs(
                        float(entry_price) * float(_stop_pct_rec) * float(qty)
                    )
                    if _planned_risk_rec > 0:
                        _r_mult_rec = realized / _planned_risk_rec
            except Exception:
                _planned_risk_rec = None
                _r_mult_rec = None
            try:
                _sess_rec = _to_eastern(
                    datetime.now(timezone.utc)
                ).date().isoformat()
            except Exception:
                _sess_rec = None
            _ledger_payload_rec = dict(record)
            _ledger_payload_rec["planned_risk_dollars"] = _planned_risk_rec
            _ledger_payload_rec["R_multiple"] = _r_mult_rec
            emit_ledger_event(
                cfg or {}, event_type="closure",
                trade_id=pos.get("link_id"), ticker=ticker,
                session_date=_sess_rec,
                payload=_ledger_payload_rec,
            )
            # Recovered fills update the bankroll just like a normal
            # closure path. The $0 stub is a no-op (no real P&L
            # signal), so skip the bankroll update there.
            if fill is not None:
                apply_realized_pnl_to_bankroll(state, cfg or {}, realized)
            open_positions.pop(ticker, None)
            summary["closed_externally"].append(ticker)
            if fill is not None:
                LOG.warning(
                    "reconcile: %s closed externally — recovered %s @ %.4f "
                    "from tracked child fill (pnl=%.2f)",
                    ticker, reason, exit_price, realized,
                )
            else:
                LOG.warning(
                    "reconcile: %s closed externally — no tracked child fill found, "
                    "recording $0 stub",
                    ticker,
                )
            continue

        bp = broker_pos_by_ticker[ticker]
        try:
            broker_qty = int(float(bp.get("quantity") or bp.get("qty") or 0))
        except (TypeError, ValueError):
            broker_qty = 0
        if broker_qty != int(pos.get("qty") or 0):
            LOG.warning("reconcile: %s qty %d -> %d", ticker, pos["qty"], broker_qty)
            pos["qty"] = broker_qty
            summary["qty_corrected"].append(ticker)

    for ticker, bp in broker_pos_by_ticker.items():
        if ticker not in open_positions:
            LOG.warning("reconcile: untracked broker position: %s qty %s",
                        ticker, bp.get("quantity") or bp.get("qty"))
            summary["untracked"].append(ticker)

    # Child order status sync. ``all_orders_by_id`` was built above
    # for the vanished-externally fill recovery.
    open_order_ids = {o.get("id") or o.get("order_id") for o in broker_open_orders}
    # Statuses that mean the child is gone for good — DAY-TIF OCO
    # children expire as ``canceled`` at session close; rejected /
    # expired / replaced are also non-recoverable. When we see one
    # of these we clear the role's ID from child_order_ids so
    # :func:`submit_pending_oco_children` re-attaches a fresh OCO
    # bracket on the next tick. The position would otherwise sit
    # naked overnight.
    _TERMINAL_CHILD = {
        "canceled", "cancelled", "rejected", "expired", "replaced",
        "done_for_day",
    }
    cleared_for_rebracket: set[str] = set()
    for ticker, pos in open_positions.items():
        children = pos.get("child_order_ids") or {}
        for role, oid in dict(children).items():
            if not oid or oid in open_order_ids:
                continue
            broker_view = all_orders_by_id.get(oid, {})
            native = (broker_view.get("native_status")
                      or broker_view.get("status") or "").lower()
            if not native:
                continue
            pos.setdefault("child_status_at_recon", {})[role] = native
            summary["child_status_corrected"].append(f"{ticker}:{role}={native}")
            if native in _TERMINAL_CHILD:
                # Clear the slot so submit_pending_oco_children sees
                # an actual_fill position with empty children and
                # re-brackets. Only fires for actual_fill-mode
                # positions; legacy candidate_close positions are
                # untouched (their bracket was atomic with the parent).
                if pos.get("bracket_pricing_mode") == "actual_fill" and pos.get("status") == "filled":
                    pos["child_order_ids"][role] = ""
                    cleared_for_rebracket.add(ticker)
    if cleared_for_rebracket:
        LOG.info(
            "reconcile cleared expired-child IDs for re-bracket: %s",
            sorted(cleared_for_rebracket),
        )
        summary["rebracket_pending"] = sorted(cleared_for_rebracket)

    # Pending signal-fade exits.
    pending = dict(state.get("pending_signal_fade_exits") or {})
    for ticker, pend in pending.items():
        oid = pend.get("exit_order_id")
        broker_view = all_orders_by_id.get(oid, {})
        native = (broker_view.get("native_status") or broker_view.get("status") or "").lower()
        if oid in open_order_ids:
            continue
        if native == "filled" or native == "FILLED".lower():
            pos = open_positions.get(ticker)
            if pos is not None:
                exit_price = float(broker_view.get("filled_avg_price") or 0.0)
                close_position(
                    ticker, state, {},  # cfg unused for closure
                    state_path=state_path, summary_path=summary_path,
                    exit_price=exit_price, reason="signal_fade",
                )
            summary["pending_signal_fade_resolved"].append(f"{ticker}:filled")
        else:
            state.get("pending_signal_fade_exits", {}).pop(ticker, None)
            summary["pending_signal_fade_resolved"].append(f"{ticker}:cleared")

    # Phase 2.4 — recompute protection_status from broker truth.
    # The 2026-05-15 incident showed four positions wearing
    # ``oco_attached`` strings with empty child_order_ids. The fix
    # is to derive the state from the live broker order snapshot at
    # every startup and persist the derived result. Any position
    # that lands in ``filled_unprotected`` is then picked up by the
    # invariant enforcer on the next tick (protection is no longer
    # confirmed, so the enforcer kicks in automatically).
    broker_orders_for_derive = {
        (o.get("id") or o.get("order_id")): o for o in broker_all_orders
    }
    summary["protection_state_recomputed"] = []
    summary["startup_repair_triggered"] = []
    for ticker, pos in list(open_positions.items()):
        derived = derive_protection_state(pos, broker_orders_for_derive)
        prev_status = pos.get("protection_status")
        pos["protection_state"] = derived
        # Map the derived state back to the legacy protection_status
        # string used by the rest of the codebase. Done as a tight
        # equivalence — no behavior change for positions whose status
        # was already correct.
        legacy_map = {
            "oco_attached_confirmed": "oco_attached",
            "fallback_stop_attached_confirmed": "fallback_stop_attached",
            "exit_order_accepted": "exiting",
            "exit_order_pending": "exiting",
            "closed": "flat",
        }
        new_legacy = legacy_map.get(derived)
        if new_legacy and new_legacy != prev_status:
            pos["protection_status"] = new_legacy
        summary["protection_state_recomputed"].append(
            f"{ticker}:{prev_status}->{derived}"
        )
        if derived == "filled_unprotected" and pos.get("status") == "filled":
            # Trigger startup repair via a ledger event; the next
            # enforcer tick will see protection unconfirmed (because
            # we did not promote the legacy string) and act.
            summary["startup_repair_triggered"].append(ticker)
            _emit_protection_ledger(
                cfg, pos, event_type="startup_repair_triggered",
                ticker=ticker,
                payload={
                    "prior_protection_status": prev_status,
                    "derived_protection_state": derived,
                    "child_order_ids": pos.get("child_order_ids") or {},
                    "fallback_stop_order_id": pos.get(
                        "fallback_stop_order_id"
                    ),
                },
            )

    save_state(state, state_path)
    LOG.info("reconcile complete: %s", summary)
    return summary


# ---------------------------------------------------------------- L2 / L3 kill


def execute_kill_l2(
    state: State,
    cfg: dict,
    http: httpx.Client,
    api_key: str,
    *,
    state_path: Path,
) -> list[str]:
    """L2: cancel + market-out every position not already exiting.
    Returns the list of tickers exited this call. Idempotent — won't
    re-exit positions already in ``status='exiting'``."""
    state["kill_switch_state"] = "L2"
    save_state(state, state_path)
    out: list[str] = []
    for ticker, pos in dict(state.get("open_positions") or {}).items():
        if pos.get("status") == "exiting":
            continue
        if pos.get("status") != "filled":
            # Pending parent — best effort cancel. We CANNOT drop the
            # position from state until every cancel call returns
            # success (or a recognized terminal state via
            # cancel_order's idempotent-success branch). A failure here
            # means the broker order may still be live; dropping state
            # in that case strands a real position with no tracking.
            cancel_failures: list[str] = []
            for role in ("target", "stop"):
                oid = (pos.get("child_order_ids") or {}).get(role)
                if oid:
                    try:
                        cancel_order(oid, http, api_key)
                    except Exception as e:
                        LOG.exception("L2 cancel %s child %s failed: %s",
                                      ticker, role, e)
                        cancel_failures.append(f"child:{role}")
            parent = pos.get("parent_order_id")
            if parent:
                try:
                    cancel_order(parent, http, api_key)
                except Exception as e:
                    LOG.exception("L2 cancel parent %s failed: %s", ticker, e)
                    cancel_failures.append("parent")
            if cancel_failures:
                # Keep the position; flag it for operator/reconciliation
                # follow-up. The next reconcile run will compare our
                # tracked order IDs against broker reality and surface
                # the live remnant, instead of it silently floating.
                pos["status"] = "cancel_failed"
                pos["cancel_failures"] = cancel_failures
                pos["cancel_failed_at"] = datetime.now(timezone.utc).isoformat()
                save_state(state, state_path)
                LOG.error(
                    "L2 leaving %s in state with cancel_failed marker "
                    "(failures=%s) — broker may still hold the order",
                    ticker, cancel_failures,
                )
            else:
                state["open_positions"].pop(ticker, None)
                save_state(state, state_path)
            out.append(ticker)
            continue
        trigger_time_stop(
            ticker, pos, cfg, http, api_key,
            state=state, state_path=state_path,
            reason="kill_switch_l2", time_in_force="DAY",
        )
        out.append(ticker)
    return out


def execute_kill_l3(
    state: State,
    cfg: dict,
    http: httpx.Client,
    api_key: str,
    *,
    state_path: Path,
) -> list[str]:
    """L3: cancel + market-out every position best-effort, persist, exit 99.
    Caller is responsible for the actual sys.exit / return 99.

    Item 8 (#4) fix: also cancels pending parent / child orders for
    positions that haven't filled yet. Previously L3 only iterated
    ``status == 'filled'`` and silently left pending orders live —
    asymmetric with L2 and dangerous in a hard-kill where the operator
    expects everything torn down.
    """
    state["kill_switch_state"] = "L3"
    save_state(state, state_path)
    out: list[str] = []
    for ticker, pos in dict(state.get("open_positions") or {}).items():
        if pos.get("status") == "filled":
            try:
                trigger_time_stop(
                    ticker, pos, cfg, http, api_key,
                    state=state, state_path=state_path,
                    reason="kill_switch_l3", time_in_force="DAY",
                )
            except Exception:
                LOG.exception("L3 exit failed for %s — best effort", ticker)
        elif pos.get("status") != "exiting":
            # Pending — best-effort cancel of children + parent. Mirrors
            # L2's cancel logic. Unlike L2 we don't keep the position
            # with cancel_failed markers; L3's contract is "best
            # effort, then exit", so we record the attempt and move on.
            for role in ("target", "stop"):
                oid = (pos.get("child_order_ids") or {}).get(role)
                if oid:
                    try:
                        cancel_order(oid, http, api_key)
                    except Exception:
                        LOG.exception(
                            "L3 cancel %s child %s failed (best effort)",
                            ticker, role,
                        )
            parent = pos.get("parent_order_id")
            if parent:
                try:
                    cancel_order(parent, http, api_key)
                except Exception:
                    LOG.exception(
                        "L3 cancel parent %s failed (best effort)", ticker,
                    )
        out.append(ticker)
    save_state(state, state_path)
    return out


# ---------------------------------------------------------------- daily summary
#
# Phase 1.6: the daily session summary is derived from the canonical
# trade ledger (``trade_ledger.jsonl``) rather than computed from
# in-memory state or the daily_summary.jsonl ``opened`` / ``closure``
# records. The ledger is append-only and immutable; the summary is a
# projection over it. Reading the summary from the ledger lets
# ``--reconcile-summary`` rebuild a botched day's record after the
# fact without re-running the session.


def recompute_daily_summary_from_ledger(
    ledger_path: Path, session_date: str,
    *,
    include_test_fixtures: bool = False,
) -> dict[str, Any]:
    """Project the trade ledger into a session-summary dict for one date.

    Aggregates every ``event_type == "closure"`` whose ``session_date``
    matches the requested date. ``correction`` events with the same
    ``trade_id`` override the original closure (last write wins);
    callers append a correction event rather than mutating the
    original. ``opened`` is counted from ``order_fill`` events with
    ``role == "parent"`` and a matching ``session_date``.

    Phase 1.5 guardrail: the function refuses to run on a ledger that
    contains mixed ``environment`` values (e.g., paper + test). The
    operator must explicitly opt in with ``include_test_fixtures=True``
    when a deliberate mixed-environment analysis is required.

    Returns the session_summary record (without ``record_type``;
    callers stamp that on write).
    """
    if ledger_path.exists() and not include_test_fixtures:
        envs_seen: set[str] = set()
        with open(ledger_path, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    ev = json.loads(line)
                except ValueError:
                    continue
                # Default to "paper" for legacy events that pre-date
                # schema v3. A bare ledger composed entirely of legacy
                # events is therefore allowed (treated as paper).
                envs_seen.add((ev.get("environment") or "paper").lower())
                if ev.get("is_test_fixture") is True:
                    envs_seen.add("test")
        if len(envs_seen - {"paper"}) > 0 and ("paper" in envs_seen):
            raise ValueError(
                "recompute_daily_summary_from_ledger: mixed environments "
                f"present in ledger {ledger_path}: {sorted(envs_seen)}. "
                "Pass include_test_fixtures=True to override."
            )
        if len(envs_seen) > 1:
            raise ValueError(
                "recompute_daily_summary_from_ledger: mixed environments "
                f"present in ledger {ledger_path}: {sorted(envs_seen)}. "
                "Pass include_test_fixtures=True to override."
            )
    by_reason: dict[str, int] = {}
    by_trigger: dict[str, dict[str, Any]] = {}
    total_pnl = 0.0
    # Closures keyed by trade_id so ``correction`` events can replace
    # the original (last write wins).
    closures_by_trade: dict[str, dict[str, Any]] = {}
    # Parent fills keyed by trade_id so a trade with multiple partial
    # parent fills only counts as one ``opened``.
    opened_trades: set[str] = set()
    opened_triggers: dict[str, str] = {}
    event_count = 0

    if ledger_path.exists():
        with open(ledger_path, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    ev = json.loads(line)
                except ValueError:
                    continue
                if ev.get("session_date") != session_date:
                    continue
                event_count += 1
                etype = ev.get("event_type")
                payload = ev.get("payload") or {}
                trade_id = ev.get("trade_id") or ""
                if etype == "order_fill" and ev.get("role") == "parent":
                    if trade_id:
                        opened_trades.add(trade_id)
                        trig = (payload.get("entry_trigger")
                                or "session_open")
                        opened_triggers[trade_id] = trig
                    continue
                if etype in {"closure", "correction"} and trade_id:
                    # Correction events fully replace the prior closure
                    # for this trade_id. The payload of a correction is
                    # the corrected closure record shape.
                    closures_by_trade[trade_id] = payload

    # Materialize counts from the deduplicated dicts.
    count_closed = len(closures_by_trade)
    for trade_id, payload in closures_by_trade.items():
        pnl = float(payload.get("realized_pnl") or 0.0)
        total_pnl += pnl
        r = payload.get("reason") or "unknown"
        by_reason[r] = by_reason.get(r, 0) + 1
        trig = (
            payload.get("entry_trigger")
            or opened_triggers.get(trade_id)
            or "session_open"
        )
        bucket = by_trigger.setdefault(
            trig, {"opened": 0, "closed": 0, "realized_pnl": 0.0},
        )
        bucket["closed"] += 1
        bucket["realized_pnl"] += pnl

    # opened tally — also fold opened trades into by_trigger so the
    # opened columns exist even when the trade has not yet closed.
    for trade_id in opened_trades:
        trig = opened_triggers.get(trade_id, "session_open")
        bucket = by_trigger.setdefault(
            trig, {"opened": 0, "closed": 0, "realized_pnl": 0.0},
        )
        bucket["opened"] += 1

    return {
        "session_date": session_date,
        "count_opened": len(opened_trades),
        "count_closed": count_closed,
        "total_realized_pnl": total_pnl,
        "by_reason": by_reason,
        "by_trigger": by_trigger,
        "derived_from_ledger": True,
        "ledger_event_count_for_date": event_count,
    }


def write_session_summary(
    state: State,
    cfg: dict,
    *,
    summary_path: Path,
    state_path: Path,
    today_iso: str,
) -> dict[str, Any] | None:
    """At session end (15:55 ET), write a session_summary record once
    per day. Phase 1.6: numbers come from the canonical trade ledger
    via :func:`recompute_daily_summary_from_ledger`, not from in-memory
    state or by re-parsing the daily_summary.jsonl. The session-state
    counters (``rescreens_today``, ``post_closure_entries_today``)
    remain in-memory because they're operational metadata, not P&L.
    """
    if state.get("summary_written_for_date") == today_iso:
        return None
    ledger_path = _ledger_path(cfg)
    base = recompute_daily_summary_from_ledger(ledger_path, today_iso)
    record = {
        "record_type": "session_summary",
        **base,
        "rescreens_today": int(state.get("rescreens_today", 0)),
        "post_closure_entries_today": int(
            state.get("post_closure_entries_today", 0)
        ),
    }
    append_closure_record(summary_path, record)
    state["summary_written_for_date"] = today_iso
    save_state(state, state_path)
    LOG.info(
        "session summary (from ledger): opened=%d closed=%d pnl=%.2f reasons=%s "
        "(ledger_events_for_date=%d)",
        record["count_opened"], record["count_closed"],
        record["total_realized_pnl"], record["by_reason"],
        record["ledger_event_count_for_date"],
    )
    return record


def reconcile_summary_for_date(
    cfg: dict, summary_path: Path, session_date: str,
) -> dict[str, Any]:
    """Rebuild the session_summary line for ``session_date`` from the
    ledger and append it as a correction.

    Doesn't mutate prior summary lines — appends a fresh one with
    ``correction_version: N+1`` where N is the count of prior
    session_summary records seen for this date in the file. Useful
    after-the-fact when an operator has appended ``correction`` events
    to the ledger to fix a closure miss.

    Returns the appended record.
    """
    ledger_path = _ledger_path(cfg)
    base = recompute_daily_summary_from_ledger(ledger_path, session_date)
    prior = 0
    if summary_path.exists():
        with open(summary_path, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    r = json.loads(line)
                except ValueError:
                    continue
                if (r.get("record_type") == "session_summary"
                        and r.get("session_date") == session_date):
                    prior += 1
    record = {
        "record_type": "session_summary",
        **base,
        "correction_version": prior + 1,
    }
    append_closure_record(summary_path, record)
    LOG.info(
        "reconciled session summary for %s (correction_version=%d, "
        "opened=%d, closed=%d, pnl=%.2f)",
        session_date, record["correction_version"],
        record["count_opened"], record["count_closed"],
        record["total_realized_pnl"],
    )
    return record


# ---------------------------------------------------------------- main loop


def _resolve_path(cfg: dict, key: str) -> Path:
    """Paths in the YAML are relative to the script's directory by
    convention; absolute paths pass through unchanged."""
    raw = cfg["paths"][key]
    p = Path(raw)
    if p.is_absolute():
        return p
    # Anchor relative paths at the script's directory.
    return Path(__file__).resolve().parent / p


def run_session_entry_pass(
    cfg: dict,
    state: State,
    state_path: Path,
    http: httpx.Client,
    api_key: str,
    *,
    today_et: date,
    kill_state: KillLevel,
    dry_run: bool = False,
) -> None:
    """First tick of a new session: equity → load+validate candidates
    → reset → select → submit. Idempotent — caller dedupes by
    ``state['session_date']``.

    Item 5 fix: candidate validation runs BEFORE
    ``reset_for_new_session`` writes today's session_date. If the
    candidates file is missing, stale, or hash-mismatched, we return
    without advancing session_date — the next tick will retry. Under
    the previous order an early-morning prefilter glitch (e.g.,
    Alpaca data not yet available, NFS lag, network hiccup) would
    permanently lock out the day's entry pass.
    """
    try:
        equity = fetch_equity(http, api_key)
    except Exception as e:
        LOG.exception("could not fetch equity: %s", e)
        return

    # Item 9: intraday confirmation gate. When enabled, the entry pass
    # waits until ``window_minutes`` after session start so opening-
    # print noise can settle. We use the same Item-5 mechanism (return
    # without advancing session_date) so the next tick retries.
    if _intraday_confirmation_cfg(cfg).get("enabled"):
        if not _intraday_window_elapsed(
            cfg, datetime.now(timezone.utc), today_et,
        ):
            ic = _intraday_confirmation_cfg(cfg)
            LOG.info(
                "intraday_confirmation: window_minutes=%s not yet elapsed; "
                "deferring entry pass to next tick",
                ic.get("window_minutes"),
            )
            return

    candidates_path = _resolve_path(cfg, "candidates_path")
    handshake = cfg.get("prefilter_handshake", {}) or {}
    try:
        # Phase 1.3: plumb feed + schema gates through.
        cands = load_candidates(
            candidates_path,
            max_age_trading_days=int(handshake.get("max_age_trading_days", 1)),
            expected_config_hash=handshake.get("expected_config_hash"),
            today_et=today_et,
            expected_data_feed=handshake.get("expected_data_feed"),
            expected_schema_version=handshake.get("expected_schema_version"),
        )
    except CandidatesError as e:
        LOG.error("candidates load failed (will retry next tick): %s", e)
        return

    # Candidates loaded cleanly — now safe to mark today's session
    # baseline. From here on the session_date is committed.
    reset_for_new_session(state, today_et.isoformat(), equity)
    save_state(state, state_path)

    # Sizing basis: the bankroll envelope when configured, broker
    # equity otherwise. With daily_allocation enabled the per-trade
    # basis is sliced by max_hold_days; the gross-exposure cap still
    # applies to the full bankroll so cumulative exposure across all
    # in-flight day-vintages is bounded.
    bankroll_basis = get_bankroll_dollars(state, fallback_equity=equity)
    sizing_basis = get_sizing_basis(state, fallback_equity=equity, cfg=cfg)
    bk_now = (state.get("bankroll") or {}).get("current_dollars")
    LOG.info(
        "Loaded %d candidates for %s (equity=%.2f, sizing_basis=%.2f, "
        "gross_basis=%.2f%s)",
        len(cands), today_et, equity, sizing_basis, bankroll_basis,
        f", bankroll=${bk_now:.2f}" if bk_now is not None else "",
    )

    # Daily total-entry cap also applies to the open-tick pass; this is
    # the first pass of the day so usually `daily_entries_count==0` and
    # the budget is the cap itself, but a restart mid-session could
    # inherit nonzero state.
    daily_cap = (cfg.get("risk") or {}).get("max_total_entries_per_day")
    remaining_budget = None
    if daily_cap is not None:
        remaining_budget = max(
            0, int(daily_cap) - int(state.get("daily_entries_count", 0)),
        )
    entries = select_entries(
        cands, state,
        equity=sizing_basis,
        latest_prices={},
        cfg=cfg,
        kill_state=kill_state,
        entry_trigger="session_open",
        remaining_entries_budget=remaining_budget,
        gross_cap_basis=bankroll_basis,
    )
    LOG.info("Selected %d entries: %s", len(entries),
             [e.ticker for e in entries])

    # Item 9: live-quote gate per ticker. When disabled this is a
    # pass-through. Phase 1.4: thread state + entry_trigger so the
    # filter can emit universal entry_decision events for rejections.
    entries = filter_by_intraday_confirmation(
        entries, cfg, http, api_key,
        state=state, entry_trigger="session_open",
    )
    LOG.info("After intraday confirmation: %d entries", len(entries))

    if dry_run:
        LOG.info("dry-run: not submitting entry orders")
        return

    # Compute the running gross at the START of the slate (before
    # any of these submissions add to it) for the entry_decision
    # records. select_entries already gated on this; we re-compute
    # so each entry_decision can carry the snapshot.
    open_positions_at_decision = state.get("open_positions") or {}
    running_gross_at_slate_start = current_gross_exposure(
        open_positions_at_decision, latest_prices={},
    )

    sizing_cfg = cfg.get("sizing") or {}
    risk_cfg = cfg.get("risk") or {}
    per_trade_pct = float(sizing_cfg.get("per_trade_pct") or 0.0)
    max_per_trade_dollars = risk_cfg.get("max_per_trade_dollars")
    # Equal-slice mode: per-trade target derives from
    # bankroll / max_concurrent_positions, NOT per_trade_pct ×
    # sizing_basis. The same override flows into compute_qty inside
    # select_entries, so the entry_decision rationale matches the
    # actual submitted qty.
    equal_slice_target = _per_trade_dollars_for_slate(
        state, cfg, fallback_equity=equity,
    )

    for slot_index, entry in enumerate(entries):
        # Reconstruct sizing rationale: which cap was binding?
        # equity_pct_target = equity * per_trade_pct, optionally
        # capped by max_per_trade_dollars and ADV cap. The binding
        # cap is whichever produced the smallest target_dollars.
        adv = (entry.candidate.features or {}).get("avg_dollar_volume")
        adv_f = float(adv) if adv is not None else None
        # ADV-tier-caps: read the tier-derived dollar cap so the
        # entry_decision rationale reflects what compute_qty actually
        # used. ``adv_cap_dollars > 0`` is the active cap; 0.0 means
        # "no cap" (operator disabled both tiers and flat frac).
        _adv_allowed, _adv_cap_v = adv_tier_cap(adv_f, cfg)
        adv_cap_dollars = _adv_cap_v if (_adv_allowed and _adv_cap_v > 0) else None
        if equal_slice_target is not None:
            candidates_target_dollars = [float(equal_slice_target)]
            binding_cap_label = "equal_slice_per_position"
        else:
            candidates_target_dollars = [sizing_basis * per_trade_pct]
            binding_cap_label = "per_trade_pct"
        if max_per_trade_dollars is not None:
            candidates_target_dollars.append(float(max_per_trade_dollars))
            if float(max_per_trade_dollars) < candidates_target_dollars[0]:
                binding_cap_label = "max_per_trade_dollars"
        if adv_cap_dollars is not None and adv_cap_dollars < min(candidates_target_dollars):
            binding_cap_label = "adv_cap"
        target_dollars = min(candidates_target_dollars + (
            [adv_cap_dollars] if adv_cap_dollars is not None else []
        ))

        # The link_id pattern matches the one submit_*_market_buy
        # uses (ticker + unix seconds), but we generate it here so
        # the entry_decision record can be filed under the same path.
        link_id_for_log = f"BOWAKA-{entry.ticker}-{int(time.time())}"
        # Phase 5.2 — shadow controls on the accepted path. The
        # snapshot is taken with the entry's actual notional and the
        # current running_gross + entries_today counter so the
        # event reflects the exact moment of the accept decision.
        try:
            shadow_for_accept = compute_shadow_controls(
                state, cfg,
                candidate_notional=float(entry.qty) * float(entry.close_price),
                is_stopout_day=False,
                current_gross_exposure_dollars=running_gross_at_slate_start,
                entries_today=int(state.get("daily_entries_count", 0)),
            )
        except Exception:
            shadow_for_accept = None
        try:
            emit_entry_decision(
                cfg, link_id=link_id_for_log, entry=entry, state=state,
                slot_index=slot_index, slate_size=len(entries),
                running_gross_at_entry=running_gross_at_slate_start,
                binding_cap=binding_cap_label,
                target_dollars=target_dollars,
                adv_cap_dollars=adv_cap_dollars,
                # Item 9 gate ran upstream; if entry survived the
                # filter we know it passed (or wasn't applied).
                intraday_confirmation_passed=(
                    True if (cfg.get("entry") or {}).get(
                        "intraday_confirmation", {}
                    ).get("enabled") else None
                ),
                shadow_controls=shadow_for_accept,
            )
        except Exception as e:
            LOG.warning("emit_entry_decision failed for %s: %s", entry.ticker, e)
        # Carry the same link_id forward so submit_* uses it for the
        # parent_submitted record (and pos["link_id"]).
        try:
            submit_entry(
                entry, cfg, http, api_key,
                state=state, state_path=state_path,
                link_id_override=link_id_for_log,
                entry_trigger="session_open",
            )
        except httpx.HTTPError as e:
            LOG.exception("entry submit network error for %s: %s",
                          entry.ticker, e)
            continue
        # Track this entry against the daily cap and same-day re-entry
        # block. We tally on submit (not on fill) so a rejected
        # submission still uses one slot — that's the safer behavior:
        # it bounds runaway resubmissions when the broker is rejecting
        # every order. The dedup also needs this immediate so the
        # rescreen path later in the day cannot pick the same name.
        if entry.ticker in (state.get("open_positions") or {}):
            state["daily_entries_count"] = int(state.get("daily_entries_count", 0)) + 1
            entered = state.setdefault("entered_today", [])
            if entry.ticker not in entered:
                entered.append(entry.ticker)
            save_state(state, state_path)


# ---------------------------------------------------------------- post-closure rescreen


def _post_closure_band(cfg: dict) -> dict | None:
    """Return the override price_band for post-closure rescreens, or
    None when the operator wants the open-tick band reused."""
    ic = _intraday_confirmation_cfg(cfg)
    return ic.get("post_closure_price_band")


def _past_last_entry_time(
    now_utc: datetime, today_et: date, last_entry_time: str, cfg: dict,
) -> bool:
    """Return True if the current wall clock is at/after ``last_entry_time``
    in the session's configured timezone. Format: ``"HH:MM"``. A bad
    value fails-closed (returns True) so a typo locks out rescreens
    rather than silently allowing late entries."""
    import pytz

    session = cfg.get("session") or {}
    tz_name = session.get("timezone") or "America/New_York"
    try:
        h, m = (int(p) for p in last_entry_time.split(":")[:2])
    except Exception:
        LOG.error(
            "post_closure_rescreen.last_entry_time=%r unparseable; "
            "fail-closed (no rescreen entries)",
            last_entry_time,
        )
        return True
    tz = pytz.timezone(tz_name)
    cutoff = tz.localize(datetime.combine(today_et, _dtime(h, m)))
    return now_utc.astimezone(tz) >= cutoff


def _fetch_open_position_marks(
    state: State, http: httpx.Client, api_key: str,
) -> dict[str, float]:
    """Refresh the latest price for every currently-open position so
    select_entries' gross-exposure calc sees real marks. Falls back to
    entry_price on any per-ticker fetch failure — better to slightly
    misstate gross than skip the whole rescreen on a single hiccup.

    Returns a ``{ticker: price}`` dict. Empty when no open positions.
    """
    open_positions = state.get("open_positions") or {}
    out: dict[str, float] = {}
    if not open_positions:
        return out
    # Pull every open ticker in one /api/v2/quotes call.
    body = {
        "apikey": api_key,
        "instruments": [
            {
                "venue_code": pos.get("venue_code") or "XNAS",
                "canonical_symbol": ticker,
            }
            for ticker, pos in open_positions.items()
        ],
    }
    try:
        r = http.post("/api/v2/quotes", json=body, headers=_api_headers(api_key))
        rows = (r.json().get("data") or []) if r.status_code == 200 else []
    except Exception as e:
        LOG.warning("rescreen: open-position mark refresh failed: %s", e)
        rows = []
    by_symbol: dict[str, dict] = {}
    for row in rows:
        sym = (row or {}).get("instrument", {}).get("canonical_symbol") or row.get("canonical_symbol")
        if sym:
            by_symbol[sym] = row.get("quote") or {}
    for ticker, pos in open_positions.items():
        quote = by_symbol.get(ticker) or {}
        # Use mid when both sides available, else last, else entry.
        try:
            bid = float(quote.get("bid") or 0)
            ask = float(quote.get("ask") or 0)
            if bid > 0 and ask > 0 and ask >= bid:
                out[ticker] = (bid + ask) / 2.0
                continue
        except (TypeError, ValueError):
            pass
        try:
            last = quote.get("last")
            if last is not None:
                out[ticker] = float(last)
                continue
        except (TypeError, ValueError):
            pass
        ep = pos.get("entry_price")
        if ep is not None:
            try:
                out[ticker] = float(ep)
            except (TypeError, ValueError):
                pass
    return out


def run_post_closure_rescreen(
    cfg: dict,
    state: State,
    state_path: Path,
    http: httpx.Client,
    api_key: str,
    *,
    today_et: date,
    kill_state: KillLevel,
    now_utc: datetime | None = None,
) -> int:
    """Item: after any position closes intraday, re-run the entry pass
    against the still-valid candidate slate so freed capital can be
    redeployed. Returns the number of new entries submitted.

    The function is a no-op when:
    - ``rescreen_pending`` is False (no closure happened since the
      last rescreen).
    - ``entry.post_closure_rescreen.enabled`` is False.
    - A kill switch is active.
    - The current time is at/after ``last_entry_time``.
    - The daily entry cap is already reached.
    - Candidates can't be loaded (e.g., file vanished mid-day).

    Side effects:
    - Clears ``rescreen_pending`` at the end of a successful pass.
    - Increments ``rescreens_today`` and ``post_closure_entries_today``.
    - For each new entry: appends the ticker to ``entered_today`` and
      bumps ``daily_entries_count``.
    - Saves state once at the end.

    Gating order matters: kill > time-cutoff > cap > candidates >
    select > confirm. Any earlier rejection clears the pending flag so
    the loop doesn't burn the next tick on the same dead-end check.
    """
    if not state.get("rescreen_pending"):
        return 0
    # Phase 3.6 — daily-risk block beats every other rescreen gate.
    if state.get("block_new_entries_today"):
        LOG.info(
            "post_closure_rescreen: entries blocked today (%s); clearing flag",
            state.get("new_entries_blocked_reason"),
        )
        state["rescreen_pending"] = False
        save_state(state, state_path)
        return 0
    rc_cfg = (cfg.get("entry") or {}).get("post_closure_rescreen") or {}
    if not rc_cfg.get("enabled"):
        state["rescreen_pending"] = False
        save_state(state, state_path)
        return 0
    if kill_state in (KillLevel.L1_NEW, KillLevel.L2_SOFT, KillLevel.L3_HARD):
        LOG.info(
            "post_closure_rescreen: kill_state=%s; clearing flag, no entries",
            kill_state.value,
        )
        state["rescreen_pending"] = False
        save_state(state, state_path)
        return 0

    now_utc = now_utc or datetime.now(timezone.utc)
    last_entry = rc_cfg.get("last_entry_time", "14:00")
    if _past_last_entry_time(now_utc, today_et, last_entry, cfg):
        LOG.info(
            "post_closure_rescreen: past last_entry_time=%s; clearing flag",
            last_entry,
        )
        state["rescreen_pending"] = False
        save_state(state, state_path)
        return 0

    risk_cfg = cfg.get("risk") or {}
    daily_cap = risk_cfg.get("max_total_entries_per_day")
    daily_count = int(state.get("daily_entries_count", 0))
    if daily_cap is not None and daily_count >= int(daily_cap):
        LOG.info(
            "post_closure_rescreen: daily entry cap %d reached (count=%d)",
            int(daily_cap), daily_count,
        )
        state["rescreen_pending"] = False
        save_state(state, state_path)
        return 0

    # Fresh equity + open-position marks for accurate gross-exposure
    # accounting. An /api/v2/balances failure aborts the rescreen
    # WITHOUT clearing the flag — next tick will retry.
    try:
        equity = fetch_equity(http, api_key)
    except Exception as e:
        LOG.warning("post_closure_rescreen: equity fetch failed: %s", e)
        return 0
    latest_prices = _fetch_open_position_marks(state, http, api_key)

    # Reload candidates — same validation as the open-tick pass. If
    # they've gone stale or the file vanished, fail-closed: clear the
    # flag and log loudly; operator action required to refresh.
    handshake = cfg.get("prefilter_handshake", {}) or {}
    try:
        # Phase 1.3: rescreen reload honors the same feed + schema
        # gates as the open-tick pass.
        cands = load_candidates(
            _resolve_path(cfg, "candidates_path"),
            max_age_trading_days=int(handshake.get("max_age_trading_days", 1)),
            expected_config_hash=handshake.get("expected_config_hash"),
            today_et=today_et,
            expected_data_feed=handshake.get("expected_data_feed"),
            expected_schema_version=handshake.get("expected_schema_version"),
        )
    except CandidatesError as e:
        LOG.warning("post_closure_rescreen: candidate reload failed: %s", e)
        state["rescreen_pending"] = False
        save_state(state, state_path)
        return 0

    remaining_budget = None
    if daily_cap is not None:
        remaining_budget = max(0, int(daily_cap) - daily_count)
        if remaining_budget == 0:
            state["rescreen_pending"] = False
            save_state(state, state_path)
            return 0

    # Bankroll envelope drives sizing in the rescreen too. The daily
    # slicing applies here as well so afternoon redeployments don't
    # break the per-day allocation discipline.
    bankroll_basis = get_bankroll_dollars(state, fallback_equity=equity)
    sizing_basis = get_sizing_basis(state, fallback_equity=equity, cfg=cfg)
    entries = select_entries(
        cands, state,
        equity=sizing_basis, latest_prices=latest_prices,
        cfg=cfg, kill_state=kill_state,
        entry_trigger="post_closure_rescreen",
        remaining_entries_budget=remaining_budget,
        gross_cap_basis=bankroll_basis,
    )
    if not entries:
        LOG.info(
            "post_closure_rescreen: 0 entries from %d candidates "
            "(equity=%.2f, sizing_basis=%.2f, daily_count=%d/%s)",
            len(cands), equity, sizing_basis, daily_count, daily_cap,
        )
        state["rescreens_today"] = int(state.get("rescreens_today", 0)) + 1
        state["rescreen_pending"] = False
        save_state(state, state_path)
        return 0

    LOG.info(
        "post_closure_rescreen: selected %d entries: %s",
        len(entries), [e.ticker for e in entries],
    )
    entries = filter_by_intraday_confirmation(
        entries, cfg, http, api_key,
        band_override=_post_closure_band(cfg),
        # Phase 1.4: rescreen-path rejections also emit universal
        # entry_decision events.
        state=state, entry_trigger="post_closure_rescreen",
    )
    LOG.info(
        "post_closure_rescreen: %d entries survive tightened confirmation",
        len(entries),
    )

    submitted = 0
    for entry in entries:
        link_id_for_log = f"BOWAKA-{entry.ticker}-{int(time.time())}"
        try:
            submit_entry(
                entry, cfg, http, api_key,
                state=state, state_path=state_path,
                link_id_override=link_id_for_log,
                entry_trigger="post_closure_rescreen",
            )
        except httpx.HTTPError as e:
            LOG.exception(
                "rescreen entry submit failed for %s: %s", entry.ticker, e,
            )
            continue
        if entry.ticker in (state.get("open_positions") or {}):
            submitted += 1
            state["daily_entries_count"] = int(state.get("daily_entries_count", 0)) + 1
            state["post_closure_entries_today"] = int(
                state.get("post_closure_entries_today", 0)
            ) + 1
            entered = state.setdefault("entered_today", [])
            if entry.ticker not in entered:
                entered.append(entry.ticker)

    state["rescreens_today"] = int(state.get("rescreens_today", 0)) + 1
    state["rescreen_pending"] = False
    save_state(state, state_path)
    LOG.info(
        "post_closure_rescreen complete: %d submitted, daily_entries_count=%d, "
        "post_closure_entries_today=%d",
        submitted, state["daily_entries_count"],
        state["post_closure_entries_today"],
    )
    return submitted


# ---------------------------------------------------------------- Phase 5 — protected-position invariant


def _protected_position_cfg(cfg: dict | None) -> dict:
    if not cfg:
        return {}
    return ((cfg.get("exits") or {}).get("protected_position") or {})


def _mark_parent_filled_for_protection(pos: dict, cfg: dict | None) -> None:
    """Phase 5.3: stamp the position with protection-deadline state
    at parent-fill time. Called from poll_fills' fill branch.

    ``cfg=None`` is tolerated (legacy poll_fills test callers) — we
    fall back to the audit default ``max_unprotected_seconds=10``."""
    pp = _protected_position_cfg(cfg)
    max_unp = float(pp.get("max_unprotected_seconds") or 10.0)
    now = datetime.now(timezone.utc)
    pos["parent_filled_at"] = now.isoformat()
    pos["protection_status"] = "none"
    pos["oco_attach_attempts"] = 0
    pos["protection_deadline_at"] = (now + timedelta(seconds=max_unp)).isoformat()


def seconds_since_iso(ts: str | None, now_utc: datetime | None = None) -> float | None:
    """Phase 5.4 helper. Returns None when ts is missing /
    unparseable."""
    if not ts:
        return None
    try:
        dt = datetime.fromisoformat(ts.replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        now = now_utc or datetime.now(timezone.utc)
        return (now - dt).total_seconds()
    except (TypeError, ValueError):
        return None


def derive_protection_state(
    pos: dict,
    broker_orders: dict[str, dict] | None = None,
) -> str:
    """Compute the protection state from actual broker order statuses.

    Phase 2 (2026-05-16): the legacy ``pos["protection_status"]``
    string is no longer authoritative. Instead we ask the broker
    which of the position's tracked order IDs are still live. The
    state name returned is one of :data:`PROTECTION_STATES`.

    ``broker_orders`` maps ``order_id -> dict`` with at least a
    ``status`` field. Pass ``{}`` (or omit) when no broker snapshot
    is available — the function will fall back conservatively to
    ``filled_unprotected`` / ``rebracket_pending`` where it can,
    rather than reporting a confirmation it cannot verify.
    """
    bo = broker_orders or {}
    status = pos.get("status")
    if status == "closed":
        return "closed"
    if status == "flat":
        return "flat"
    if status in {"pending_entry", "submitted", "pending_fill"}:
        return "pending_entry"

    exit_id = pos.get("exit_order_id")
    if exit_id:
        bs = (bo.get(exit_id) or {}).get("status", "")
        if bs in _ACTIVE_OR_ACCEPTED_BROKER_STATUSES:
            return "exit_order_accepted"
        # Submission attempted but no broker echo yet.
        if pos.get("exit_submitted_at") and not bs:
            return "exit_order_pending"

    children = pos.get("child_order_ids") or {}
    stop_id = children.get("stop") or ""
    target_id = children.get("target") or ""
    stop_active = bool(stop_id) and (bo.get(stop_id) or {}).get(
        "status"
    ) in _ACTIVE_OR_ACCEPTED_BROKER_STATUSES
    target_active = bool(target_id) and (bo.get(target_id) or {}).get(
        "status"
    ) in _ACTIVE_OR_ACCEPTED_BROKER_STATUSES
    if stop_active and target_active:
        return "oco_attached_confirmed"

    fb_id = pos.get("fallback_stop_order_id")
    if fb_id and (bo.get(fb_id) or {}).get(
        "status"
    ) in _ACTIVE_OR_ACCEPTED_BROKER_STATUSES:
        return "fallback_stop_attached_confirmed"

    if pos.get("rebracket_pending"):
        return "rebracket_pending"

    if pos.get("protection_repair_failed_at"):
        return "protection_repair_failed"

    return "filled_unprotected"


def has_confirmed_protection(
    pos: dict,
    broker_orders: dict[str, dict] | None = None,
) -> bool:
    """A position is protected when broker order state confirms an
    active OCO, fallback stop, or accepted exit order. Optional
    ``broker_orders`` short-circuits the call when the caller has not
    yet fetched live orders — in that case we trust ONLY explicit
    terminal states (closed/flat); otherwise return False
    conservatively to force a recheck rather than skip enforcement.

    Phase 2 (2026-05-16): the bug fix. The legacy implementation
    trusted the stored ``protection_status`` string verbatim, which
    let four positions (ASPN/ONDS/PCT/QS on 2026-05-15) ride wearing
    ``oco_attached`` with empty child_order_ids and no real OCO live
    at the broker. The new contract requires either the explicit
    closed/flat terminal markers OR a broker-confirmed derive call.
    """
    state = pos.get("status")
    if state == "closed":
        return True
    if state == "flat":
        return True
    if broker_orders is None:
        # No live snapshot — never trust the stored protection_status
        # string. This is the heart of the fix for the 2026-05-15
        # incident.
        return False
    derived = derive_protection_state(pos, broker_orders)
    return derived in {
        "oco_attached_confirmed",
        "fallback_stop_attached_confirmed",
        "exit_order_accepted",
    }


def protection_deadline_breached(
    pos: dict, cfg: dict, now_utc: datetime | None = None,
) -> bool:
    """Phase 5.4: True when the protection deadline has passed."""
    deadline = pos.get("protection_deadline_at")
    if not deadline:
        return False
    try:
        dt = datetime.fromisoformat(deadline.replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        now = now_utc or datetime.now(timezone.utc)
        return now > dt
    except (TypeError, ValueError):
        return False


def submit_fallback_stop(
    ticker: str,
    pos: dict,
    cfg: dict,
    http: httpx.Client,
    api_key: str,
) -> str | None:
    """Phase 5.5: stand-alone STOP order for a position whose OCO
    attach has timed out.

    Returns the broker order id on success, None on failure. The
    order is GTC so it persists across session boundaries until the
    operator intervenes or the next OCO retry succeeds.
    """
    pp = _protected_position_cfg(cfg)
    venue_code = pos.get("venue_code") or cfg["sizing"]["default_venue_code"]
    qty = int(pos.get("qty") or 0)
    entry_price = float(pos.get("entry_price") or 0)
    stop_pct = float(pos.get("stop_pct") or cfg["exits"]["stop_pct"])
    if qty <= 0 or entry_price <= 0:
        LOG.warning(
            "submit_fallback_stop: %s has qty=%d entry_price=%.4f; skipping",
            ticker, qty, entry_price,
        )
        return None
    stop_price = round(entry_price * (1.0 - stop_pct), 2)
    order_type = (pp.get("fallback_stop_order_type") or "stop").lower()
    body = {
        "apikey": api_key,
        "instrument": {"venue_code": venue_code, "canonical_symbol": ticker},
        "side": "SELL",
        "quantity": str(qty),
        "quantity_unit": "WHOLE",
        "time_in_force": "GTC",
        "session": "REGULAR",
    }
    if order_type == "stop_limit":
        offset = float(pp.get("fallback_stop_limit_offset_pct") or 0.02)
        limit_price = round(stop_price * (1.0 - offset), 2)
        body["order_type"] = "STOP_LIMIT"
        body["trigger_price"] = str(stop_price)
        body["price"] = str(limit_price)
    else:
        body["order_type"] = "STOP"
        body["trigger_price"] = str(stop_price)
    try:
        r = http.post("/api/v2/orders", json=body, headers=_api_headers(api_key))
    except Exception as e:
        LOG.exception("submit_fallback_stop network error for %s: %s", ticker, e)
        return None
    parsed = r.json() if r.content else {}
    if r.status_code != 200:
        LOG.error(
            "submit_fallback_stop failed for %s: HTTP %d %s",
            ticker, r.status_code, parsed,
        )
        return None
    data = parsed.get("data") or {}
    native = data.get("native_response") or {}
    oid = (
        native.get("id") or native.get("order_id")
        or data.get("order_id") or ""
    )
    if not oid:
        LOG.error(
            "submit_fallback_stop accepted but no order_id surfaced for %s: %s",
            ticker, parsed,
        )
        return None
    LOG.warning(
        "fallback stop submitted for %s: order_id=%s stop_price=%.4f",
        ticker, oid, stop_price,
    )
    return oid


def _emit_protection_event(
    cfg: dict, pos: dict, *, event_type: str, ticker: str,
    payload: dict[str, Any],
) -> None:
    """Phase 5.6 telemetry. Mirrors to both the per-trade jsonl
    and the canonical Phase 1.5 ledger."""
    link_id = pos.get("link_id") or ""
    rec = {
        "record_type": "protection_event",
        "ts": _now_utc_iso(),
        "ticker": ticker, "link_id": link_id,
        "event_type": event_type,
        **payload,
    }
    _append_trade_log(cfg, link_id, rec)
    emit_ledger_event(
        cfg, event_type="protection_event",
        trade_id=link_id, ticker=ticker,
        payload=rec,
    )


# Phase 2.6 — canonical protection_* ledger event types. Every
# protection-related transition is emitted via emit_ledger_event
# with one of these event_type values.
PROTECTION_EVENT_TYPES: frozenset[str] = frozenset({
    "protection_state_changed",
    "oco_submit_requested",
    "oco_submit_accepted",
    "oco_submit_rejected",
    "child_cancel_requested",
    "child_cancel_confirmed",
    "replacement_exit_submitted",
    "replacement_exit_accepted",
    "replacement_exit_rejected",
    "protection_gap_started",
    "protection_gap_resolved",
    "fallback_stop_submitted",
    "fallback_stop_accepted",
    "fallback_stop_rejected",
    "forced_flatten_submitted",
    "forced_flatten_accepted",
    "forced_flatten_rejected",
    "startup_repair_triggered",
    "startup_repair_resolved",
})


def _emit_protection_ledger(
    cfg: dict | None, pos: dict, *, event_type: str, ticker: str,
    payload: dict[str, Any],
) -> None:
    """Phase 2.6: thin wrapper that drops one row in the canonical
    ledger with the protection_* event_type. Separate from
    ``_emit_protection_event`` because the legacy helper also writes
    to per-trade jsonl — these protection_* events are ledger-only.
    """
    if event_type not in PROTECTION_EVENT_TYPES:
        # Programming error, not a runtime issue — surface loudly in
        # logs so the operator notices a typo.
        LOG.error(
            "_emit_protection_ledger: unknown event_type %r (allowed=%s)",
            event_type, sorted(PROTECTION_EVENT_TYPES),
        )
        return
    link_id = pos.get("link_id") or ""
    emit_ledger_event(
        cfg, event_type=event_type,
        trade_id=link_id, ticker=ticker,
        payload={"ts": _now_utc_iso(), **payload},
    )


def replace_protection_with_exit(
    ticker: str,
    pos: dict,
    cfg: dict,
    http: httpx.Client,
    api_key: str,
    *,
    exit_submit_callable,
    state: State,
    state_path: Path,
) -> tuple[bool, str | None]:
    """Phase 2.5: atomic protection replacement.

    Submit the replacement exit FIRST. Only on broker acceptance do
    we cancel the OCO children. On rejection, the OCO remains live
    and we return ``(False, reason)``. Used by signal_fade in
    Phase 4 and by any future cancel-and-replace exit path.

    ``exit_submit_callable`` is a zero-arg callable returning the
    same dict shape as :func:`submit_market_sell` /
    :func:`submit_marketable_limit_sell`. The caller chooses the
    order type / TIF so this helper does not need to know.
    """
    # Step 1: submit the replacement exit.
    try:
        result = exit_submit_callable()
    except Exception as e:
        LOG.exception(
            "replace_protection_with_exit: submit raised for %s: %s",
            ticker, e,
        )
        _emit_protection_ledger(
            cfg, pos, event_type="replacement_exit_rejected",
            ticker=ticker,
            payload={"reason": f"submit_exception: {e!r}"},
        )
        return False, f"submit_exception: {e!r}"

    http_status = (
        result.get("_http_status")
        if isinstance(result, dict) else None
    )
    if not isinstance(result, dict) or http_status is None or http_status >= 400:
        # Submit failed; protection remains live.
        _emit_protection_ledger(
            cfg, pos, event_type="replacement_exit_rejected",
            ticker=ticker,
            payload={"http_status": http_status, "response": result},
        )
        return False, f"http_status={http_status}"

    # Step 2: extract order_id.
    data = result.get("data") or {}
    native = data.get("native_response") or {}
    order_id = (
        native.get("id") or native.get("order_id")
        or data.get("order_id") or result.get("order_id") or ""
    )
    if not order_id:
        _emit_protection_ledger(
            cfg, pos, event_type="replacement_exit_rejected",
            ticker=ticker,
            payload={
                "http_status": http_status,
                "reason": "no_order_id_surfaced",
                "response": result,
            },
        )
        return False, "no_order_id_surfaced"

    _emit_protection_ledger(
        cfg, pos, event_type="replacement_exit_submitted",
        ticker=ticker,
        payload={"order_id": order_id, "http_status": http_status},
    )

    # Step 3: persist the new exit BEFORE attempting child cancels.
    # If we crash between here and the cancel calls, the next tick
    # finds the new exit_order_id and re-attempts to clean up.
    pos["exit_order_id"] = order_id
    pos["exit_submitted_at"] = _now_utc_iso()
    pos["status"] = "exiting"
    save_state(state, state_path)

    _emit_protection_ledger(
        cfg, pos, event_type="replacement_exit_accepted",
        ticker=ticker,
        payload={"order_id": order_id, "http_status": http_status},
    )

    # Step 4: cancel OCO children. Failures here are logged but do
    # NOT roll back the exit — the broker may have already accepted
    # / filled the replacement.
    children = pos.get("child_order_ids") or {}
    for role, child_id in list(children.items()):
        if not child_id:
            continue
        _emit_protection_ledger(
            cfg, pos, event_type="child_cancel_requested",
            ticker=ticker,
            payload={"role": role, "child_order_id": child_id},
        )
        try:
            cancel_order(child_id, http, api_key)
            _emit_protection_ledger(
                cfg, pos, event_type="child_cancel_confirmed",
                ticker=ticker,
                payload={"role": role, "child_order_id": child_id},
            )
        except Exception as e:
            LOG.warning(
                "replace_protection_with_exit: cancel %s child %s "
                "failed for %s (continuing — replacement is live): %s",
                role, child_id, ticker, e,
            )

    return True, None


def enforce_protected_position_invariant(
    state: State,
    cfg: dict,
    http: httpx.Client | None,
    api_key: str | None,
    *,
    state_path: Path,
    now_utc: datetime | None = None,
    broker_orders: dict[str, dict] | None = None,
) -> dict[str, Any]:
    """Phase 5.6: iterate filled positions and ensure each one is
    protected (OCO attached OR fallback stop attached).

    Phase 2 (2026-05-16): protection confirmation now requires a
    broker-truth snapshot. ``broker_orders`` may be passed in by
    the caller (avoids re-fetching when the caller already has it),
    or fetched on demand here from ``fetch_open_orders``.

    Returns a summary dict for logging.
    """
    pp = _protected_position_cfg(cfg)
    summary = {
        "checked": 0, "retried": 0, "fallback_attached": 0,
        "flattened": 0, "violations": 0,
    }
    if not pp.get("enabled"):
        return summary
    now = now_utc or datetime.now(timezone.utc)
    open_positions = state.get("open_positions") or {}
    dirty = False

    max_attempts = int(pp.get("max_oco_attach_attempts") or 2)
    fallback_enabled = bool(pp.get("fallback_stop_enabled"))
    flatten = bool(pp.get("flatten_if_unprotected"))
    block_on_viol = bool(pp.get("block_entries_on_violation"))

    # Phase 2: fetch the broker's current order snapshot once per
    # invocation. has_confirmed_protection / derive_protection_state
    # need this to confirm an order is actually live — the stored
    # ``protection_status`` string is no longer trusted on its face.
    if broker_orders is None and http is not None and api_key is not None:
        try:
            rows = fetch_open_orders(http, api_key, status="open")
            broker_orders = {
                (o.get("id") or o.get("order_id")): o for o in rows
            }
        except Exception as e:
            LOG.warning(
                "enforce_protected_position_invariant: open orders "
                "fetch failed; running with empty broker snapshot: %s", e,
            )
            broker_orders = {}
    broker_orders = broker_orders or {}

    for ticker, pos in list(open_positions.items()):
        if pos.get("status") != "filled":
            continue
        # Skip exiting / cancel_failed positions — they're already
        # in a state the protection enforcer can't help with.
        if pos.get("status") == "exiting":
            continue
        if has_confirmed_protection(pos, broker_orders):
            # If we have OCO children, normalize the status so the
            # state record reflects reality.
            if (pos.get("child_order_ids") or {}).get("target") and (
                pos.get("child_order_ids") or {}
            ).get("stop"):
                if pos.get("protection_status") not in {
                    "oco_attached", "fallback_stop_attached"
                }:
                    pos["protection_status"] = "oco_attached"
                    dirty = True
            continue
        summary["checked"] += 1

        # 1. Attempt to attach OCO (if we still have retries).
        attempts = int(pos.get("oco_attach_attempts") or 0)
        if attempts < max_attempts and http is not None and api_key is not None:
            pos["oco_attach_attempts"] = attempts + 1
            summary["retried"] += 1
            try:
                res = submit_oco_children(
                    ticker, pos, cfg, http, api_key,
                    state=state, state_path=state_path,
                )
            except Exception as e:
                LOG.exception(
                    "enforce_protected_position_invariant OCO submit "
                    "raised for %s: %s", ticker, e,
                )
                res = None
            # On success the child IDs are populated; has_confirmed_
            # protection will return True next pass.
            children = pos.get("child_order_ids") or {}
            if children.get("target") and children.get("stop"):
                pos["protection_status"] = "oco_attached"
                _emit_protection_event(
                    cfg, pos, event_type="oco_attached", ticker=ticker,
                    payload={"oco_attach_attempts": pos["oco_attach_attempts"]},
                )
                dirty = True
                continue
            # Soft fail — leave attempts incremented and fall through
            # to the deadline check.

        # 2. Deadline not breached yet → wait.
        if not protection_deadline_breached(pos, cfg, now_utc=now):
            continue

        # 3. Deadline breached + fallback enabled → submit STOP.
        if fallback_enabled and not pos.get("fallback_stop_order_id"):
            if http is not None and api_key is not None:
                fb_oid = submit_fallback_stop(ticker, pos, cfg, http, api_key)
            else:
                fb_oid = None
            if fb_oid:
                pos["fallback_stop_order_id"] = fb_oid
                pos["protection_status"] = "fallback_stop_attached"
                summary["fallback_attached"] += 1
                _emit_protection_event(
                    cfg, pos, event_type="fallback_stop_attached",
                    ticker=ticker,
                    payload={"order_id": fb_oid},
                )
                dirty = True
                continue

        # 4. Still unprotected → flatten + violation.
        if flatten and http is not None and api_key is not None:
            pos["protection_status"] = "flattening"
            pos["protection_violation"] = True
            summary["violations"] += 1
            summary["flattened"] += 1
            if block_on_viol and not state.get("block_new_entries_today"):
                state["block_new_entries_today"] = True
                state["new_entries_blocked_reason"] = "unprotected_position_violation"
            _emit_protection_event(
                cfg, pos, event_type="unprotected_deadline_breached",
                ticker=ticker,
                payload={
                    "max_unprotected_seconds": pp.get("max_unprotected_seconds"),
                    "oco_attach_attempts": pos.get("oco_attach_attempts"),
                },
            )
            try:
                trigger_time_stop(
                    ticker, pos, cfg, http, api_key,
                    state=state, state_path=state_path,
                    reason="protection_violation_flatten",
                    time_in_force="DAY",
                )
            except Exception as e:
                LOG.exception(
                    "protection-violation flatten failed for %s (best effort): %s",
                    ticker, e,
                )
            dirty = True

    if dirty:
        save_state(state, state_path)
    return summary


# ---------------------------------------------------------------- Phase 5.8 — stop-manager ablation


def desired_stop_from_mfe(pos: dict, cfg: dict) -> float | None:
    """Return the highest stop price implied by ``stop_manager.rules``
    given the position's current MFE, or None when no rule fires.

    ``rules`` is a list of ``{mfe_min, stop_at}`` dicts; the rule
    with the largest mfe_min that the position has crossed wins.
    Stops never move down — caller is responsible for clamping
    against the prior stop.
    """
    sm_cfg = ((cfg.get("exits") or {}).get("stop_manager") or {})
    if not sm_cfg.get("enabled"):
        return None
    entry = pos.get("entry_price")
    peak = pos.get("peak_since_entry")
    if entry is None or peak is None:
        return None
    try:
        entry_f = float(entry)
        peak_f = float(peak)
    except (TypeError, ValueError):
        return None
    if entry_f <= 0:
        return None
    mfe = (peak_f - entry_f) / entry_f
    best: float | None = None
    for rule in sm_cfg.get("rules") or []:
        mfe_min = float(rule.get("mfe_min") or 0)
        stop_at = float(rule.get("stop_at") or 0)
        if mfe >= mfe_min:
            candidate = entry_f * (1.0 + stop_at)
            if best is None or candidate > best:
                best = candidate
    return best


def maybe_advance_stop(
    pos: dict,
    cfg: dict,
    http: httpx.Client | None,
    api_key: str | None,
    *,
    state: State,
    state_path: Path,
    ticker: str,
) -> str | None:
    """Phase 5.8 stop-manager step. No-op when the feature is
    disabled or the position lacks OCO children.

    Returns the new stop order id when a replacement was submitted,
    None otherwise.
    """
    sm_cfg = ((cfg.get("exits") or {}).get("stop_manager") or {})
    if not sm_cfg.get("enabled"):
        return None
    if pos.get("protection_status") != "oco_attached":
        return None
    children = pos.get("child_order_ids") or {}
    if not (children.get("target") and children.get("stop")):
        return None

    target_stop = desired_stop_from_mfe(pos, cfg)
    if target_stop is None:
        return None
    current_stop = pos.get("stop_price")
    if current_stop is None:
        return None
    try:
        current_f = float(current_stop)
        target_f = float(target_stop)
    except (TypeError, ValueError):
        return None
    # Stops never move down.
    if target_f <= current_f:
        return None

    old_stop_id = children.get("stop")
    # Cancel old, then submit a replacement STOP order. On
    # replacement-submit failure leave child_order_ids untouched so
    # the next tick retries.
    try:
        cancel_order(old_stop_id, http, api_key)
    except Exception as e:
        LOG.exception(
            "maybe_advance_stop: cancel old stop %s failed for %s: %s",
            old_stop_id, ticker, e,
        )
        return None
    venue_code = pos.get("venue_code") or cfg["sizing"]["default_venue_code"]
    qty = int(pos.get("qty") or 0)
    body = {
        "apikey": api_key,
        "instrument": {"venue_code": venue_code, "canonical_symbol": ticker},
        "side": "SELL",
        "order_type": "STOP",
        "quantity": str(qty), "quantity_unit": "WHOLE",
        "trigger_price": str(round(target_f, 2)),
        "time_in_force": "GTC",
        "session": "REGULAR",
    }
    try:
        r = http.post("/api/v2/orders", json=body, headers=_api_headers(api_key))
    except Exception as e:
        LOG.exception("maybe_advance_stop submit failed for %s: %s", ticker, e)
        return None
    parsed = r.json() if r.content else {}
    if r.status_code != 200:
        LOG.error(
            "maybe_advance_stop new stop rejected for %s (status=%d): %s",
            ticker, r.status_code, parsed,
        )
        return None
    data = parsed.get("data") or {}
    native = data.get("native_response") or {}
    new_oid = (
        native.get("id") or native.get("order_id")
        or data.get("order_id") or ""
    )
    if not new_oid:
        return None
    pos["child_order_ids"]["stop"] = new_oid
    pos["stop_price"] = round(target_f, 2)
    save_state(state, state_path)
    rec = {
        "record_type": "stop_replaced",
        "ts": _now_utc_iso(),
        "ticker": ticker, "link_id": pos.get("link_id") or "",
        "old_stop_order_id": old_stop_id,
        "new_stop_order_id": new_oid,
        "old_stop_price": current_f,
        "new_stop_price": pos["stop_price"],
    }
    _append_trade_log(cfg, pos.get("link_id"), rec)
    emit_ledger_event(
        cfg, event_type="protection_event",
        trade_id=pos.get("link_id"), ticker=ticker,
        payload=rec,
    )
    LOG.info(
        "stop_manager: %s stop advanced %.4f -> %.4f (new_id=%s)",
        ticker, current_f, pos["stop_price"], new_oid,
    )
    return new_oid


def run_loop(
    cfg: dict,
    *,
    once: bool = False,
    dry_run: bool = False,
    now_provider=lambda: datetime.now(timezone.utc),
    http_client: httpx.Client | None = None,
    api_key: str | None = None,
) -> int:
    """Main loop. Returns the exit code.

    ``once`` returns after one tick (used by tests). ``now_provider`` is
    pluggable so tests can advance fake time without sleeping.
    ``http_client`` and ``api_key`` are injected by tests; production
    builds them from env vars and YAML.
    """
    state_path = _resolve_path(cfg, "state_path")
    switch_dir = _resolve_path(cfg, "kill_switch_dir")
    interval = float(cfg["session"].get("loop_interval_seconds", 5))

    state = load_state(state_path)
    LOG.info("Loaded state: %d open positions, kill=%s",
             len(state.get("open_positions", {})),
             state.get("kill_switch_state"))

    # HTTP client: tests inject; production builds from env.
    own_http = False
    if http_client is None:
        broker_cfg = cfg.get("broker", {}) or {}
        env_var = broker_cfg.get("base_url_env", "HOST_SERVER")
        base_url = os.environ.get(
            env_var, broker_cfg.get("base_url_default", "http://127.0.0.1:5000")
        )
        timeout = float(broker_cfg.get("timeout_seconds", 15))
        http_client = make_http_client(base_url, timeout=timeout)
        own_http = True
    if api_key is None:
        api_key = os.environ.get("OPENALGO_API_KEY", "")

    summary_path = _resolve_path(cfg, "daily_summary_path")

    # Bankroll initialization. Runs BEFORE reconcile so that any
    # recovered fills update the bankroll value the rest of the loop
    # uses for sizing. A misconfigured cfg.bankroll raises
    # BankrollConfigError here — fail-loud so the operator fixes the
    # YAML rather than over-sizing trades with broker equity.
    try:
        initialize_bankroll(
            state, cfg, http_client, api_key,
            state_path=state_path,
        )
    except BankrollConfigError as e:
        LOG.error("bankroll cfg invalid; refusing to start: %s", e)
        return 5
    except Exception as e:
        LOG.exception("bankroll init failed; refusing to start: %s", e)
        return 5

    # Phase 4: startup reconciliation (no-op when state is empty).
    try:
        reconcile_at_startup(
            state, http_client, api_key,
            state_path=state_path, summary_path=summary_path,
            cfg=cfg,
        )
    except Exception as e:
        LOG.exception("startup reconciliation failed (continuing): %s", e)

    try:
        while not _shutdown_requested:
            now = now_provider()
            kill = check_kill_switches(switch_dir)

            if kill is KillLevel.L3_HARD:
                LOG.error("L3 (hard kill) detected — best-effort exit + code 99")
                try:
                    execute_kill_l3(state, cfg, http_client, api_key,
                                    state_path=state_path)
                except Exception as e:
                    LOG.exception("L3 execution failed: %s", e)
                save_state(state, state_path)
                return 99

            if kill is KillLevel.L2_SOFT:
                if state.get("kill_switch_state") != "L2":
                    LOG.warning("L2 (soft kill) detected — market-out all positions")
                try:
                    execute_kill_l2(state, cfg, http_client, api_key,
                                    state_path=state_path)
                except Exception as e:
                    LOG.exception("L2 execution failed: %s", e)
                # L2 idle: continue ticking, no entries, but allow L3 escalation.

            if kill is KillLevel.L1_NEW:
                if state.get("kill_switch_state") != "L1":
                    state["kill_switch_state"] = "L1"
                    save_state(state, state_path)
                LOG.warning("L1 (new entries blocked) detected")

            in_session = is_in_session(
                now,
                start=cfg["session"]["start"],
                end=cfg["session"]["end"],
            )
            if not in_session:
                LOG.debug("outside session window")
            else:
                today_et = _to_eastern(now).date()
                today_iso = today_et.isoformat()
                if state.get("session_date") != today_iso:
                    LOG.info("first session tick for %s — entry pass",
                             today_iso)
                    # Daily reconcile: reconcile_at_startup only fires
                    # at process bootstrap, but a long-running strategy
                    # crosses session boundaries during which OCO
                    # children may have terminally canceled (DAY-TIF
                    # expiry pre-GTC, or any operator-side cancel).
                    # Run reconcile on the first tick of each new
                    # session so submit_pending_oco_children's
                    # idempotency check sees an empty slot for any
                    # carryover position whose bracket expired
                    # overnight. With GTC OCOs this is mostly a
                    # safety net; with DAY OCOs it's load-bearing.
                    try:
                        reconcile_at_startup(
                            state, http_client, api_key,
                            state_path=state_path,
                            summary_path=summary_path,
                            cfg=cfg,
                        )
                    except Exception as e:
                        LOG.exception(
                            "daily reconcile error (continuing): %s", e,
                        )
                    run_session_entry_pass(
                        cfg, state, state_path, http_client, api_key,
                        today_et=today_et,
                        kill_state=kill,
                        dry_run=dry_run,
                    )
                else:
                    # Subsequent ticks within the same session.
                    try:
                        events = poll_fills(state, http_client, api_key,
                                             state_path=state_path, cfg=cfg)
                    except httpx.HTTPError as e:
                        LOG.exception("poll_fills network error: %s", e)
                        events = []
                    if events:
                        process_fill_events_for_closures(
                            events, state, cfg,
                            state_path=state_path,
                            summary_path=summary_path,
                        )
                    # Item 4 (actual_fill mode): once parents fill we
                    # need to attach the OCO bracket using the real
                    # fill price. Idempotent — only fires for filled
                    # positions still missing child IDs.
                    try:
                        attached = submit_pending_oco_children(
                            state, cfg, http_client, api_key,
                            state_path=state_path,
                        )
                        if attached:
                            LOG.info("OCO brackets attached post-fill: %s", attached)
                    except Exception as e:
                        LOG.exception("submit_pending_oco_children failed: %s", e)
                    # Phase 5.7 — protected-position invariant runs
                    # AFTER the OCO-attach pass and BEFORE the entry
                    # passes. A protection violation flips
                    # block_new_entries_today so the same-tick entry
                    # pass cannot launch a new long while a prior
                    # one is unprotected.
                    try:
                        enforce_protected_position_invariant(
                            state, cfg, http_client, api_key,
                            state_path=state_path, now_utc=now,
                        )
                    except Exception as e:
                        LOG.exception(
                            "enforce_protected_position_invariant error: %s", e,
                        )
                    # Phase 5.8 — stop-manager step. No-op when
                    # cfg.exits.stop_manager.enabled == False.
                    try:
                        for ticker_sm, pos_sm in list(
                            (state.get("open_positions") or {}).items()
                        ):
                            maybe_advance_stop(
                                pos_sm, cfg, http_client, api_key,
                                state=state, state_path=state_path,
                                ticker=ticker_sm,
                            )
                    except Exception as e:
                        LOG.exception("maybe_advance_stop error: %s", e)
                    # Per-trade rich logging: 1-minute intraday tick
                    # snapshot per filled position. Idempotent — each
                    # position has its own ``last_tick_logged_at`` so
                    # this is a no-op until 60s have elapsed since
                    # the previous snapshot for that ticker.
                    try:
                        tick_interval = int(
                            (cfg.get("logging") or {}).get(
                                "intraday_tick_interval_seconds", 60,
                            )
                        )
                        run_intraday_tick_logging(
                            cfg, state, http_client, api_key,
                            state_path=state_path, now_utc=now,
                            interval_seconds=tick_interval,
                        )
                    except Exception as e:
                        LOG.exception("intraday tick logging error: %s", e)
                    # Phase 7.3 — per-position liquidity monitor.
                    # No-op when disabled. Raises NotImplementedError
                    # for the tighten_stop / exit_partial actions —
                    # caught here so the strategy keeps running and
                    # the operator sees the error in the log.
                    try:
                        run_liquidity_monitor_pass(
                            cfg, state, http_client, api_key,
                            state_path=state_path, now_utc=now,
                        )
                    except Exception as e:
                        LOG.exception("liquidity monitor error: %s", e)
                    # Phase 4: daily P&L tracking.
                    try:
                        eq = fetch_equity(http_client, api_key)
                        update_daily_pnl(state, eq, cfg, state_path=state_path)
                    except Exception as e:
                        LOG.warning("equity check failed (continuing): %s", e)
                    # Time-stop and signal-fade are SUPERSEDED under L2.
                    today_et = _to_eastern(now).date()
                    if kill not in (KillLevel.L2_SOFT,):
                        try:
                            run_time_stop_pass(
                                cfg, state, http_client, api_key,
                                today_et=today_et, state_path=state_path,
                            )
                        except Exception as e:
                            LOG.exception("time-stop pass error: %s", e)
                    # Post-closure rescreen: redeploy capital after any
                    # intraday closure. Debounces multiple per-tick
                    # closures via state["rescreen_pending"]; gated
                    # internally by daily_cap, last_entry_time, and
                    # the intraday_confirmation filter so stale signals
                    # are rejected before order submission. Runs every
                    # tick (cheap no-op when the flag is clear), but
                    # skipped under L2 — kill_l2 cancels OCO and flat-
                    # tens positions; redeploying would directly
                    # contradict operator intent.
                    if kill not in (KillLevel.L2_SOFT, KillLevel.L3_HARD):
                        try:
                            run_post_closure_rescreen(
                                cfg, state, state_path, http_client, api_key,
                                today_et=today_et, kill_state=kill,
                                now_utc=now,
                            )
                        except Exception as e:
                            LOG.exception("post_closure_rescreen error: %s", e)
                    # Session-end summary (15:55 ET tick).
                    et_dt = _to_eastern(now)
                    end_h, end_m = (int(x) for x in cfg["session"]["end"].split(":"))
                    if et_dt.hour == end_h and et_dt.minute == end_m:
                        try:
                            write_session_summary(
                                state, cfg,
                                summary_path=summary_path,
                                state_path=state_path,
                                today_iso=today_et.isoformat(),
                            )
                        except Exception as e:
                            LOG.exception("session summary write failed: %s", e)

            # Phase 4.4 — two-phase signal-fade. The exit pass runs
            # at 15:45 ET (default) and uses an atomic marketable-
            # limit SELL; the telemetry pass runs at 16:05 ET and
            # only emits events for the counterfactual study. Both
            # superseded under L2.
            sf_eval_time = _signal_fade_eval_time(cfg)
            sf_tel_time = _signal_fade_telemetry_time(cfg)

            if kill not in (KillLevel.L2_SOFT,) and is_signal_fade_window(
                now, sf_eval_time,
            ):
                today_et = _to_eastern(now).date()
                # Analytic logging: write today's mark for every
                # filled position BEFORE the signal-fade exit pass.
                # Doing this first means a position that signal-fades
                # this tick still gets a closing mark recorded with
                # today's high/low/close + fresh feature values, which
                # the analyst needs to study why the gates failed.
                try:
                    write_daily_marks(
                        cfg, state, http_client, api_key,
                        today_et=today_et,
                        summary_path=summary_path,
                        state_path=state_path,
                        now_utc=now,
                    )
                except Exception as e:
                    LOG.exception("daily_mark pass error: %s", e)
                try:
                    run_signal_fade_pass(
                        cfg, state, http_client, api_key,
                        today_et=today_et, state_path=state_path,
                        now_utc=now, mode="exit",
                    )
                except Exception as e:
                    LOG.exception("signal-fade exit pass error: %s", e)

            if kill not in (KillLevel.L2_SOFT,) and is_signal_fade_window(
                now, sf_tel_time,
            ):
                today_et = _to_eastern(now).date()
                try:
                    run_signal_fade_pass(
                        cfg, state, http_client, api_key,
                        today_et=today_et, state_path=state_path,
                        now_utc=now, mode="telemetry",
                    )
                except Exception as e:
                    LOG.exception("signal-fade telemetry pass error: %s", e)

            if once:
                break

            # Sleep in small chunks so the shutdown flag is honored quickly.
            slept = 0.0
            while slept < interval and not _shutdown_requested:
                chunk = min(0.5, interval - slept)
                time.sleep(chunk)
                slept += chunk
    finally:
        if own_http:
            http_client.close()

    # Clean shutdown.
    save_state(state, state_path)
    LOG.info("shutdown complete")
    return 0


# ---------------------------------------------------------------- main


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Bowaka /python strategy")
    parser.add_argument("--config", required=True, help="Path to YAML config")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Skip live order placement (used by later-phase paths)",
    )
    parser.add_argument(
        "--once",
        action="store_true",
        help="Run one main-loop tick then exit (tests)",
    )
    parser.add_argument(
        "--reconcile-summary",
        metavar="YYYY-MM-DD",
        default=None,
        help=(
            "Phase 1.6: rebuild the session_summary line for the given "
            "ET date from the canonical trade ledger and append it as a "
            "correction (does not run the main loop)."
        ),
    )
    args = parser.parse_args(argv)

    cfg = load_config(args.config)
    setup_logging(cfg)
    cfg_hash = config_hash(cfg)
    LOG.info("Starting bowaka strategy (config_hash=%s)", cfg_hash)

    # Phase 1.2 — environment guardrail. Refuse to start if the YAML
    # declares an environment that doesn't agree with the resolved
    # ledger path. This catches the foot-gun where a test fixture
    # accidentally writes to data/paper/ (or paper data accidentally
    # writes to data/test/) — which silently contaminates the
    # operator's research dataset.
    env = _strategy_environment(cfg)
    if env not in VALID_ENVIRONMENTS:
        LOG.error(
            "strategy.environment must be one of %s; got %r",
            sorted(VALID_ENVIRONMENTS), env,
        )
        return 8
    try:
        ledger_path_resolved = _ledger_path(cfg)
    except Exception as e:
        LOG.error("ledger path unresolvable: %s", e)
        return 8
    if f"/{env}/" not in ledger_path_resolved.as_posix() and \
            f"\\{env}\\" not in str(ledger_path_resolved):
        # The explicit override path bypasses the partition; only
        # complain when the partition is actually wrong (env=test but
        # path is under data/paper/, or vice versa). The check is
        # asymmetric: an operator with paths.trade_ledger_path
        # override gets to opt out.
        explicit = (cfg.get("paths") or {}).get("trade_ledger_path")
        if not explicit:
            LOG.error(
                "environment=%r but resolved ledger path %s is not "
                "under data/%s/. Refusing to start.",
                env, ledger_path_resolved, env,
            )
            return 8

    # Phase 1.4 — per-run config snapshot. Written once at startup
    # before any ledger event, so every event in the run reports a
    # snapshot path that exists.
    try:
        snap = _write_config_snapshot(cfg)
        if snap:
            LOG.info("config snapshot written: %s", snap)
    except Exception as e:
        LOG.warning("config snapshot write raised (continuing): %s", e)

    # Phase 1.6 — one-shot reconcile path. Skips handshake / API-key
    # check because the ledger + summary files are local artifacts
    # and don't need broker connectivity.
    if args.reconcile_summary:
        try:
            summary_path = _resolve_path(cfg, "daily_summary_path")
        except KeyError:
            LOG.error("--reconcile-summary requires paths.daily_summary_path")
            return 6
        try:
            rec = reconcile_summary_for_date(cfg, summary_path, args.reconcile_summary)
        except Exception as e:
            LOG.exception("--reconcile-summary failed: %s", e)
            return 7
        LOG.info(
            "reconcile-summary appended: %s (correction_version=%d, "
            "opened=%d, closed=%d, pnl=%.2f)",
            rec.get("session_date"),
            rec.get("correction_version", 1),
            rec.get("count_opened", 0),
            rec.get("count_closed", 0),
            rec.get("total_realized_pnl", 0.0),
        )
        return 0

    # Item 8 (handshake): cross-check signal_gates + indicators against
    # the prefilter yaml so the EOD signal-fade exits never use
    # thresholds the prefilter never applied. Failure raises
    # HandshakeMismatch — operator must reconcile and restart.
    try:
        verify_prefilter_handshake(cfg)
    except HandshakeMismatch as e:
        LOG.error("prefilter handshake failed: %s", e)
        return 5

    if not os.environ.get("OPENALGO_API_KEY"):
        LOG.error("OPENALGO_API_KEY must be set in env")
        return 2
    host = os.environ.get("HOST_SERVER", "http://127.0.0.1:5000")
    LOG.info("HOST_SERVER=%s", host)

    strat_exch = os.environ.get("OPENALGO_STRATEGY_EXCHANGE")
    if strat_exch != "CRYPTO":
        LOG.warning(
            "OPENALGO_STRATEGY_EXCHANGE=%r (expected 'CRYPTO' for the "
            "/python host workaround). Continuing.",
            strat_exch,
        )

    install_signal_handlers()
    return run_loop(cfg, once=args.once, dry_run=args.dry_run)


if __name__ == "__main__":
    sys.exit(main())
