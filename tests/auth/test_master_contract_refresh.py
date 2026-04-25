"""Phase 4 — utils.auth_utils.get_master_contract_cutoff respects
broker-declared master_contract_refresh_policy.

Legacy India brokers keep the 08:00 IST default. Plugins that declare
an explicit policy use that policy. ``frequency=never`` disables the
daily refresh entirely.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest


@pytest.fixture(autouse=True)
def _reset_env(monkeypatch):
    monkeypatch.delenv("MASTER_CONTRACT_CUTOFF_TIME", raising=False)
    monkeypatch.delenv("CRYPTO_MASTER_CONTRACT_CUTOFF_TIME", raising=False)


def _stub_caps(monkeypatch, broker, **kwargs):
    caps = SimpleNamespace(
        broker_type=kwargs.pop("broker_type", "IN_stock"),
        master_contract_refresh_policy=kwargs.pop("policy", None),
    )
    monkeypatch.setattr(
        "utils.plugin_loader.get_broker_capabilities",
        lambda b: caps if b == broker else None,
    )


def test_legacy_india_broker_default_8am_ist(monkeypatch) -> None:
    """No plugin-declared policy → 08:00 in IST (back-compat)."""
    _stub_caps(monkeypatch, "zerodha", policy=None)
    from utils.auth_utils import get_master_contract_cutoff

    h, m, tz = get_master_contract_cutoff("zerodha")
    assert (h, m) == (8, 0)
    assert str(tz) == "Asia/Kolkata"


def test_plugin_us_policy_overrides(monkeypatch) -> None:
    _stub_caps(
        monkeypatch,
        "alpaca",
        broker_type="US_stock",
        policy={
            "timezone": "America/New_York",
            "cutoff_local": "06:30",
            "frequency": "daily",
        },
    )
    from utils.auth_utils import get_master_contract_cutoff

    h, m, tz = get_master_contract_cutoff("alpaca")
    assert (h, m) == (6, 30)
    assert str(tz) == "America/New_York"


def test_plugin_never_returns_none(monkeypatch) -> None:
    _stub_caps(
        monkeypatch,
        "alpaca",
        broker_type="US_stock",
        policy={"frequency": "never", "skip_if_24x7": True},
    )
    from utils.auth_utils import get_master_contract_cutoff

    h, m, tz = get_master_contract_cutoff("alpaca")
    assert h is None and m is None and tz is None


def test_crypto_broker_without_policy_gets_never(monkeypatch) -> None:
    """A crypto plugin that didn't declare a policy still gets the
    24x7-skip default — preserves CRYPTO_BROKERS legacy behavior."""
    _stub_caps(
        monkeypatch,
        "deltaexchange",
        broker_type="crypto",
        policy=None,
    )
    from utils.auth_utils import get_master_contract_cutoff

    h, m, tz = get_master_contract_cutoff("deltaexchange")
    assert h is None and tz is None


def test_should_download_handles_never(monkeypatch) -> None:
    _stub_caps(
        monkeypatch,
        "alpaca",
        broker_type="US_stock",
        policy={"frequency": "never"},
    )
    from datetime import datetime
    monkeypatch.setattr(
        "utils.auth_utils.get_last_download_time",
        lambda b: datetime(2026, 4, 25, 12, 0, 0),
    )
    monkeypatch.setattr(
        "utils.auth_utils.get_last_downloaded_broker", lambda: "alpaca"
    )
    from utils.auth_utils import should_download_master_contract

    should, reason = should_download_master_contract("alpaca")
    assert should is False
    assert "never" in reason


def test_unknown_broker_falls_back_to_legacy(monkeypatch) -> None:
    """Broker not in plugin_loader cache (or get_broker_capabilities
    returns None) → no policy lookup, legacy IST default applies."""
    monkeypatch.setattr(
        "utils.plugin_loader.get_broker_capabilities", lambda b: None
    )
    from utils.auth_utils import get_master_contract_cutoff

    h, m, tz = get_master_contract_cutoff("unknown_broker")
    assert (h, m) == (8, 0)
    assert str(tz) == "Asia/Kolkata"
