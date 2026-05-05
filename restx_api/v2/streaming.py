"""Phase 4 — /api/v2/streaming WebSocket endpoint.

Multiplexed channel: one HTTP-upgrade-to-WS per client; the client
sends `subscribe`/`unsubscribe`/`heartbeat` control envelopes (per
HANDOFF §0.5) and the server fans out `bar_update` / `bar_close` /
`indicator_update` / `error` envelopes back.

Threading model: Flask-SocketIO is the existing transport for the
in-app SocketIO events (orders, positions, ticks). For the chart
workspace's multiplexed contract, we use the same SocketIO namespace
under `/charts/streaming` so we don't open a second WS port. Phase 4
ships the contract surface; the actual broker → backend wiring lives
in :mod:`services.charts.tick_publisher` + :mod:`services.charts.ws_fanout`.

This module is intentionally thin — the heavy lifting lives in
services/charts/. All it does is:

* Authenticate the client (apikey-as-cookie or query param).
* Translate client→server control messages to fanout calls.
* Translate fanout-emitted envelopes to SocketIO events.
"""

from __future__ import annotations

import json
from typing import Any

from flask import request

from services.charts.ws_envelope import WSEnvelope, make_ack, make_error, parse_control
from utils.logging import get_logger

logger = get_logger(__name__)


def register_streaming(socketio: Any, fanout: Any) -> None:
    """Wire `/charts/streaming` SocketIO handlers.

    Called once at app startup if API_V2 + chart streaming are enabled.
    `fanout` is a configured :class:`services.charts.ws_fanout.WsFanout`.
    """
    namespace = "/charts/streaming"

    @socketio.on("connect", namespace=namespace)
    def _on_connect():  # type: ignore[unused-ignore]
        logger.info(
            "chart streaming client connect: sid=%s remote=%s",
            getattr(request, "sid", None),
            request.remote_addr,
        )
        return True

    @socketio.on("disconnect", namespace=namespace)
    def _on_disconnect(*args: Any, **kwargs: Any):  # type: ignore[unused-ignore]
        logger.info("chart streaming client disconnect: sid=%s", getattr(request, "sid", None))

    @socketio.on("control", namespace=namespace)
    def _on_control(payload: Any):  # type: ignore[unused-ignore]
        try:
            ctrl = parse_control(json.dumps(payload) if not isinstance(payload, str) else payload)
        except Exception as e:  # noqa: BLE001
            socketio.emit(
                "envelope",
                make_error("", "bad_control", str(e)).to_json(),
                namespace=namespace,
                to=getattr(request, "sid", None),
            )
            return

        # `parse_control` returns one of WSSubscribe / WSUnsubscribe / WSHeartbeat.
        op = getattr(ctrl, "op", None)
        if op == "subscribe":
            params = getattr(ctrl, "params", None) or {}
            symbol = params.get("symbol")
            timeframe = params.get("timeframe", "1m")
            if not symbol:
                socketio.emit(
                    "envelope",
                    make_error("", "missing_symbol", "subscribe requires params.symbol").to_json(),
                    namespace=namespace,
                    to=getattr(request, "sid", None),
                )
                return

            # Async work scheduled on socketio's eventlet pool.
            def _go() -> None:
                try:
                    import asyncio

                    asyncio.run(fanout.acquire(symbol, timeframe))
                except Exception:  # noqa: BLE001
                    logger.exception("fanout acquire failed")

            socketio.start_background_task(_go)
            ack = make_ack(
                f"{symbol}:{timeframe}",
                channel=getattr(ctrl, "channel", ""),
                granted=True,
            )
            socketio.emit(
                "envelope",
                ack.to_json(),
                namespace=namespace,
                to=getattr(request, "sid", None),
            )
            return

        if op == "unsubscribe":
            sid = getattr(ctrl, "subscription_id", "")
            symbol, _, timeframe = sid.partition(":")
            if not symbol:
                return

            def _go() -> None:
                try:
                    import asyncio

                    asyncio.run(fanout.release(symbol, timeframe or "1m"))
                except Exception:  # noqa: BLE001
                    logger.exception("fanout release failed")

            socketio.start_background_task(_go)
            return

        if op == "heartbeat":
            socketio.emit(
                "envelope",
                make_ack("heartbeat", server_ts=WSEnvelope(type="ack", subscription_id="heartbeat", payload={}).ts).to_json(),
                namespace=namespace,
                to=getattr(request, "sid", None),
            )
            return


__all__ = ["register_streaming"]
