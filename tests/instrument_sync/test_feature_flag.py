"""INSTRUMENT_CORE_V2 feature-flag gating.

The login path in `utils/auth_utils.handle_auth_success` is heavy (it
touches Flask session, SocketIO, the legacy downloader, and the DB auth
table). Here we isolate the Phase 2b wiring: verify that

* flag off → no new-pipeline adapter is invoked
* flag on + known broker → the adapter registry hand-off is made
* flag on + unknown broker → no error, new pipeline is simply skipped
"""

from __future__ import annotations

import os
from unittest import mock

from utils import feature_flags


def test_is_enabled_default_false(monkeypatch) -> None:
    monkeypatch.delenv("INSTRUMENT_CORE_V2", raising=False)
    assert feature_flags.is_enabled("INSTRUMENT_CORE_V2") is False


def test_is_enabled_various_truthy(monkeypatch) -> None:
    for value in ("1", "true", "TRUE", "yes", "YES", "on", " on "):
        monkeypatch.setenv("INSTRUMENT_CORE_V2", value)
        assert feature_flags.is_enabled("INSTRUMENT_CORE_V2") is True, value


def test_is_enabled_various_falsy(monkeypatch) -> None:
    for value in ("0", "false", "no", "off", "", "anything-else"):
        monkeypatch.setenv("INSTRUMENT_CORE_V2", value)
        assert feature_flags.is_enabled("INSTRUMENT_CORE_V2") is False, value


def test_adapter_registry_exports_expected_keys() -> None:
    from services.instrument_sync_adapters import ADAPTERS

    assert "zerodha" in ADAPTERS
    assert "deltaexchange" in ADAPTERS


def test_maybe_start_instrument_sync_skips_when_flag_off(monkeypatch) -> None:
    """When the flag is off, the helper must NOT import / invoke any adapter."""
    from utils import auth_utils

    monkeypatch.delenv("INSTRUMENT_CORE_V2", raising=False)

    with mock.patch("utils.auth_utils.Thread") as thread_cls:
        auth_utils._maybe_start_instrument_sync_v2("zerodha")
        thread_cls.assert_not_called()


def test_maybe_start_instrument_sync_fires_when_flag_on_and_adapter_exists(
    monkeypatch,
) -> None:
    from utils import auth_utils

    monkeypatch.setenv("INSTRUMENT_CORE_V2", "1")
    with mock.patch("utils.auth_utils.Thread") as thread_cls:
        instance = thread_cls.return_value
        auth_utils._maybe_start_instrument_sync_v2("zerodha")
        thread_cls.assert_called_once()
        instance.start.assert_called_once()


def test_maybe_start_instrument_sync_skips_when_adapter_missing(monkeypatch) -> None:
    from utils import auth_utils

    monkeypatch.setenv("INSTRUMENT_CORE_V2", "1")
    with mock.patch("utils.auth_utils.Thread") as thread_cls:
        auth_utils._maybe_start_instrument_sync_v2("broker_with_no_adapter")
        thread_cls.assert_not_called()
