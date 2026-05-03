"""Production-shape WSGI runner using eventlet directly.

Gunicorn (the production WSGI server) is Unix-only — Windows
operators can't run it natively. But the eventlet ``wsgi.server``
that gunicorn-eventlet drives internally works fine on every
platform. This script spins up the Flask app under that same
runtime so we can validate any thread / socket / monkey-patch
assumption locally before deploying to a Linux gunicorn host.

Specifically validates:

* ``threading.Thread`` instances created at app startup (the
  trade-updates client and master-contract scheduler) come up
  cleanly under eventlet's monkey-patched stdlib.
* ``websocket.WebSocketApp.run_forever()`` doesn't deadlock under
  green-thread sockets.
* ``httpx.Client`` requests inside threads complete without
  blocking the WSGI loop.
* The shared ZeroMQ context survives the eventlet patching that
  hooks ``socket.socket``.

Usage (Windows, Linux, macOS):
    uv run python scripts/run_eventlet_wsgi.py [--host 127.0.0.1] [--port 5000]

Stop with Ctrl-C; the eventlet server cleans up its listening
socket on KeyboardInterrupt.
"""

from __future__ import annotations

# IMPORTANT: monkey patch must happen before any other stdlib import
# that creates sockets / threads / locks. Putting it at the top of
# main() would be too late — Flask's import chain creates a
# threading.Lock during module-level import.
import eventlet

eventlet.monkey_patch()

import argparse
import os
import sys

# Ensure the repo root is on sys.path so this script can be invoked
# from any working directory ("uv run python scripts/...", a cron
# entry, a systemd unit, etc.).
_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)

from eventlet import wsgi

from app import app
from utils.logging import get_logger


logger = get_logger(__name__)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Run the OpenAlgo Flask app under eventlet's "
        "WSGI server (production-shape smoke)."
    )
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=5000)
    args = parser.parse_args()

    logger.info(
        "eventlet smoke: starting Flask under eventlet wsgi.server on %s:%d",
        args.host,
        args.port,
    )
    sock = eventlet.listen((args.host, args.port))
    try:
        wsgi.server(sock, app, log_output=False)
    except KeyboardInterrupt:
        logger.info("eventlet smoke: stopping (KeyboardInterrupt)")
    finally:
        try:
            sock.close()
        except Exception:  # pragma: no cover
            pass
    return 0


if __name__ == "__main__":
    sys.exit(main())
