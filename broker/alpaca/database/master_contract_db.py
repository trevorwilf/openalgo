"""Alpaca master-contract entrypoint.

Thin wrapper that the framework's
``market_regions.india.legacy_v1.utils.auth_utils.async_master_contract_download``
hook calls via dynamic import:

    importlib.import_module(f"broker.{broker}.database.master_contract_db")
    module.master_contract_download()

For Alpaca the heavy lifting lives in
``broker/alpaca/sync/instrument_sync.sync_instruments`` which writes
to the canonical ``database.instruments_repo`` (modern v2 path), not
to the legacy India ``SymToken`` table. This wrapper just calls that
sync function and emits the SocketIO status event the UI listens for.
"""

from __future__ import annotations

from typing import Any

from utils.logging import get_logger

logger = get_logger(__name__)


def master_contract_download() -> Any:
    """Run the Alpaca instrument sync and emit the status event.

    Returns whatever the SocketIO emit returns (None on most server
    setups; the auth_utils flow polls the database to confirm
    completion regardless).
    """
    try:
        from broker.alpaca.sync.instrument_sync import sync_instruments
    except ImportError:  # pragma: no cover - defensive
        logger.exception("Could not import broker.alpaca.sync.instrument_sync")
        return _emit_status(
            "error", "Alpaca instrument sync module unavailable"
        )

    logger.info("Alpaca master_contract_download starting (sync_instruments)")
    try:
        summary = sync_instruments()
    except Exception as exc:  # noqa: BLE001 — top-level boundary
        logger.exception("Alpaca master_contract_download failed: %s", exc)
        return _emit_status("error", str(exc))

    msg = (
        f"Alpaca instrument sync ok: fetched={summary.fetched_count} "
        f"new={summary.new_instruments} "
        f"map_rows={summary.map_rows_written}"
    )
    logger.info(msg)
    return _emit_status("success", msg)


def _emit_status(status: str, message: str) -> Any:
    """Emit the master_contract_download SocketIO event so the
    Flask UI can update its progress badge.

    Falls back to a logged-only path if SocketIO is unavailable
    (eg. when run from a CLI smoke test).
    """
    try:
        from extensions import socketio
    except ImportError:  # pragma: no cover - CLI / test path
        logger.debug(
            "extensions.socketio unavailable — skipping UI emit (status=%s)",
            status,
        )
        return None
    try:
        return socketio.emit(
            "master_contract_download",
            {"status": status, "message": message},
        )
    except Exception:  # pragma: no cover - SocketIO mid-shutdown
        logger.exception(
            "socketio.emit failed for master_contract_download (%s)", status
        )
        return None


__all__ = ["master_contract_download"]
