"""Unit tests for the master-contract daily refresh scheduler.

Stubs out the legacy auth_utils helpers so the test suite doesn't
need a working broker auth session — the goal is to lock the
scheduler's contract: respect the broker policy, compute the next
cutoff correctly, and never crash on a transient broker failure.
"""

from __future__ import annotations

from datetime import datetime
from unittest import mock

import pytest
import pytz

from services import master_contract_scheduler


def test_next_cutoff_today_in_future():
    """When today's cutoff hasn't passed, target is today."""
    tz = pytz.timezone("America/New_York")
    now = tz.localize(datetime(2026, 5, 5, 6, 0, 0))  # 06:00 ET
    target = master_contract_scheduler._next_cutoff(now, 8, 0)
    assert target.hour == 8
    assert target.minute == 0
    assert target.date() == now.date()


def test_next_cutoff_today_in_past_rolls_to_tomorrow():
    tz = pytz.timezone("America/New_York")
    now = tz.localize(datetime(2026, 5, 5, 9, 30, 0))  # 09:30 ET, past 08:00
    target = master_contract_scheduler._next_cutoff(now, 8, 0)
    assert target.hour == 8
    assert target.minute == 0
    assert target.date() == now.date().replace(day=now.day + 1)


def test_cycle_skips_when_policy_is_never(monkeypatch):
    """``frequency=never`` (e.g. 24/7 crypto) makes the scheduler
    sleep an hour and re-check rather than triggering a download.
    """
    sleeps: list[float] = []
    monkeypatch.setattr(master_contract_scheduler, "_sleep", lambda s: sleeps.append(s))

    monkeypatch.setattr(
        "market_regions.india.legacy_v1.utils.auth_utils.get_master_contract_cutoff",
        lambda broker: (None, None, None),
    )
    monkeypatch.setattr(
        "market_regions.india.legacy_v1.utils.auth_utils.should_download_master_contract",
        lambda broker: pytest.fail("should not be called when policy=never"),
    )
    monkeypatch.setattr(
        "market_regions.india.legacy_v1.utils.auth_utils.async_master_contract_download",
        lambda broker: pytest.fail("should not be called when policy=never"),
    )

    master_contract_scheduler._cycle("crypto_broker")
    assert sleeps == [3600]


def test_cycle_triggers_download_when_due(monkeypatch):
    """When today's cutoff has passed AND should_download_master_contract
    says yes, the scheduler kicks off the download.
    """
    sleeps: list[float] = []
    monkeypatch.setattr(master_contract_scheduler, "_sleep", lambda s: sleeps.append(s))

    tz = pytz.timezone("America/New_York")
    monkeypatch.setattr(
        "market_regions.india.legacy_v1.utils.auth_utils.get_master_contract_cutoff",
        lambda broker: (8, 0, tz),
    )
    monkeypatch.setattr(
        "market_regions.india.legacy_v1.utils.auth_utils.should_download_master_contract",
        lambda broker: (True, "different day"),
    )
    download_calls: list[str] = []
    monkeypatch.setattr(
        "market_regions.india.legacy_v1.utils.auth_utils.async_master_contract_download",
        lambda broker: download_calls.append(broker),
    )

    master_contract_scheduler._cycle("alpaca")
    assert download_calls == ["alpaca"]
    # _cycle waited for the cutoff (one sleep call).
    assert len(sleeps) == 1


def test_cycle_skips_when_should_download_says_no(monkeypatch):
    """Same-day, after cutoff, recent download → no re-fetch."""
    monkeypatch.setattr(master_contract_scheduler, "_sleep", lambda s: None)

    tz = pytz.timezone("America/New_York")
    monkeypatch.setattr(
        "market_regions.india.legacy_v1.utils.auth_utils.get_master_contract_cutoff",
        lambda broker: (8, 0, tz),
    )
    monkeypatch.setattr(
        "market_regions.india.legacy_v1.utils.auth_utils.should_download_master_contract",
        lambda broker: (False, "already downloaded today"),
    )
    download_calls: list[str] = []
    monkeypatch.setattr(
        "market_regions.india.legacy_v1.utils.auth_utils.async_master_contract_download",
        lambda broker: download_calls.append(broker),
    )

    master_contract_scheduler._cycle("alpaca")
    assert download_calls == []


def test_disabled_via_env(monkeypatch):
    """``MASTER_CONTRACT_SCHEDULER_DISABLED=1`` is the operator escape
    hatch. When set, ``start_master_contract_scheduler`` is a no-op.
    """
    monkeypatch.setenv("MASTER_CONTRACT_SCHEDULER_DISABLED", "1")
    master_contract_scheduler._THREAD = None
    master_contract_scheduler.start_master_contract_scheduler()
    assert master_contract_scheduler._THREAD is None
