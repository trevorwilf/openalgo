"""Alpaca master_contract_download entrypoint — wraps sync_instruments."""

from __future__ import annotations

import sys
from types import SimpleNamespace
from unittest import mock


def test_master_contract_download_calls_sync_and_emits_success(monkeypatch):
    """Happy path: sync_instruments returns a SyncSummary, the wrapper
    emits ``status: success`` to SocketIO with the counts.
    """
    from broker.alpaca.database import master_contract_db

    fake_summary = SimpleNamespace(
        sync_id="00000000-0000-0000-0000-000000000000",
        fetched_count=1234,
        new_instruments=12,
        map_rows_written=1234,
        status="ok",
    )

    fake_sync = mock.Mock(return_value=fake_summary)
    fake_socketio = mock.Mock()

    monkeypatch.setitem(
        sys.modules,
        "broker.alpaca.sync.instrument_sync",
        SimpleNamespace(sync_instruments=fake_sync),
    )
    monkeypatch.setitem(
        sys.modules,
        "extensions",
        SimpleNamespace(socketio=fake_socketio),
    )

    master_contract_db.master_contract_download()

    fake_sync.assert_called_once_with()
    fake_socketio.emit.assert_called_once()
    event_name, payload = fake_socketio.emit.call_args.args
    assert event_name == "master_contract_download"
    assert payload["status"] == "success"
    assert "fetched=1234" in payload["message"]
    assert "new=12" in payload["message"]


def test_master_contract_download_emits_error_on_exception(monkeypatch):
    from broker.alpaca.database import master_contract_db

    fake_sync = mock.Mock(side_effect=RuntimeError("alpaca down"))
    fake_socketio = mock.Mock()

    monkeypatch.setitem(
        sys.modules,
        "broker.alpaca.sync.instrument_sync",
        SimpleNamespace(sync_instruments=fake_sync),
    )
    monkeypatch.setitem(
        sys.modules,
        "extensions",
        SimpleNamespace(socketio=fake_socketio),
    )

    master_contract_db.master_contract_download()

    event_name, payload = fake_socketio.emit.call_args.args
    assert event_name == "master_contract_download"
    assert payload["status"] == "error"
    assert "alpaca down" in payload["message"]


def test_master_contract_download_no_socketio_does_not_raise(monkeypatch):
    """When extensions.socketio is unavailable (eg. CLI smoke run),
    the wrapper degrades to log-only without raising.
    """
    from broker.alpaca.database import master_contract_db

    fake_summary = SimpleNamespace(
        sync_id="x", fetched_count=1, new_instruments=1, map_rows_written=1, status="ok"
    )
    fake_sync = mock.Mock(return_value=fake_summary)

    monkeypatch.setitem(
        sys.modules,
        "broker.alpaca.sync.instrument_sync",
        SimpleNamespace(sync_instruments=fake_sync),
    )
    # Simulate ImportError for extensions.socketio.
    monkeypatch.setitem(sys.modules, "extensions", None)

    # No exception means the smoke path works.
    master_contract_db.master_contract_download()
    fake_sync.assert_called_once()
