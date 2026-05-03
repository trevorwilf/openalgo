"""Daily master-contract refresh scheduler.

The legacy login path triggers exactly one download per session — at
``handle_auth_success`` time. That's enough for an operator who logs
in fresh every day, but a Flask process kept running across the daily
cutoff (e.g. paper-trading desks left up over multiple sessions)
serves stale symbol data after the cutoff fires.

This module spawns a daemon thread on app startup that:

  1. Reads the active broker's
     ``master_contract_refresh_policy`` from
     :func:`utils.plugin_loader.get_broker_capabilities`.
  2. Computes the next cutoff (``cutoff_local`` in the policy's
     ``timezone``).
  3. Sleeps until that cutoff (in short slices so the thread can
     exit quickly on app shutdown).
  4. Calls :func:`should_download_master_contract` and triggers
     :func:`async_master_contract_download` if a refresh is due.
  5. Loops.

Per-broker ``frequency=never`` (e.g. crypto plugins that don't need a
daily snapshot) is respected — the thread sleeps for one hour and
re-checks the policy in case the operator changes it without a
restart.

Disable knob: ``MASTER_CONTRACT_SCHEDULER_DISABLED=1`` in env. The
scheduler is best-effort; failure to start logs a warning but never
blocks app startup, and individual cycle errors are logged and
swallowed so a transient broker outage doesn't kill the thread.
"""

from __future__ import annotations

import os
import threading
import time
from datetime import datetime, timedelta
from typing import Any

from utils.logging import get_logger


logger = get_logger(__name__)


_THREAD: threading.Thread | None = None
_STOP = threading.Event()


def _now_in_tz(tz: Any) -> datetime:
    return datetime.now(tz)


def _next_cutoff(now: datetime, hour: int, minute: int) -> datetime:
    """Return the next datetime today/tomorrow matching (hour, minute)
    in ``now``'s timezone. If today's cutoff has already passed,
    rolls forward to tomorrow.
    """
    target = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
    if target <= now:
        target = target + timedelta(days=1)
    return target


def _cycle(broker: str) -> None:
    """One scheduler iteration for ``broker``."""
    from market_regions.india.legacy_v1.utils.auth_utils import (
        async_master_contract_download,
        get_master_contract_cutoff,
        should_download_master_contract,
    )

    cutoff_hour, cutoff_minute, tz = get_master_contract_cutoff(broker)
    if cutoff_hour is None:
        # frequency=never — re-check in an hour in case the policy
        # changes mid-process.
        logger.debug(
            "master-contract scheduler: %s policy=never; sleeping 1h", broker
        )
        _sleep(3600)
        return

    now = _now_in_tz(tz)
    target = _next_cutoff(now, cutoff_hour, cutoff_minute)
    delta = (target - now).total_seconds()
    logger.info(
        "master-contract scheduler: next refresh for %s at %s (in %.0fs)",
        broker,
        target.isoformat(),
        delta,
    )
    _sleep(delta)
    if _STOP.is_set():
        return

    try:
        should_download, reason = should_download_master_contract(broker)
    except Exception:  # pragma: no cover
        logger.exception("master-contract scheduler should_download_check failed")
        return

    if not should_download:
        logger.info(
            "master-contract scheduler: %s — skipping refresh: %s",
            broker,
            reason,
        )
        return

    logger.info(
        "master-contract scheduler: %s — triggering refresh: %s", broker, reason
    )
    try:
        # Run the download on the scheduler thread directly. The
        # underlying broker module is responsible for being side-
        # effect-light (it writes to instruments_repo / SymToken,
        # logs progress).
        async_master_contract_download(broker)
    except Exception:  # pragma: no cover
        logger.exception("master-contract scheduler refresh failed")


def _sleep(seconds: float) -> None:
    """Sleep up to ``seconds`` in 1-second slices so ``_STOP`` can
    interrupt promptly when the app shuts down.
    """
    end = time.monotonic() + max(0.0, seconds)
    while not _STOP.is_set() and time.monotonic() < end:
        time.sleep(min(1.0, end - time.monotonic()))


def _scheduler_loop() -> None:
    """The thread entry point. Picks the active broker on each
    iteration so a session change (broker swap) is honored without a
    process restart.
    """
    from utils.plugin_loader import get_broker_capabilities  # noqa: F401

    while not _STOP.is_set():
        broker = _active_broker()
        if not broker:
            logger.debug("master-contract scheduler: no active broker; sleeping 5min")
            _sleep(300)
            continue
        try:
            _cycle(broker)
        except Exception:  # pragma: no cover
            logger.exception("master-contract scheduler cycle crashed")
            _sleep(60)


def _active_broker() -> str | None:
    """Return the broker code from the most-recent persisted auth row.

    A Flask process runs as a single-broker deployment (ADR 0001), so
    "the active broker" is simply whichever broker last authenticated
    successfully.
    """
    try:
        from database.auth_db import get_last_downloaded_broker

        broker = get_last_downloaded_broker()
        return broker.lower() if broker else None
    except Exception:  # pragma: no cover
        return None


def start_master_contract_scheduler() -> None:
    """Spawn the daemon thread. Idempotent — calling twice is a
    no-op.
    """
    global _THREAD
    if os.environ.get("MASTER_CONTRACT_SCHEDULER_DISABLED", "").lower() in (
        "1",
        "true",
        "yes",
    ):
        logger.info("master-contract scheduler disabled via env var")
        return
    if _THREAD is not None and _THREAD.is_alive():
        return

    _STOP.clear()
    _THREAD = threading.Thread(
        target=_scheduler_loop,
        name="master-contract-scheduler",
        daemon=True,
    )
    _THREAD.start()
    logger.info("master-contract scheduler started")


def stop_master_contract_scheduler(timeout: float = 5.0) -> None:
    """Tear the thread down. For tests; never called in production."""
    _STOP.set()
    if _THREAD is not None and _THREAD.is_alive():
        _THREAD.join(timeout=timeout)


__all__ = [
    "start_master_contract_scheduler",
    "stop_master_contract_scheduler",
]
