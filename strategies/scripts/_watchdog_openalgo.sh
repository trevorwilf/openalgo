#!/usr/bin/env bash
# ============================================================
# _watchdog_openalgo.sh
#
# Linux/macOS equivalent of _watchdog_openalgo.cmd. Wraps the
# OpenAlgo runtime in a restart loop. The bowaka strategy
# cannot trade without OpenAlgo; for unattended operation we
# auto-restart if the runtime dies for any reason.
#
# Caps at 10 restarts per launch. Uses ``uv run`` to handle
# dependencies + venv discovery transparently.
#
# Behavior matches the .cmd version:
#   - Exit code 0 = clean SIGINT/SIGTERM → no restart
#   - Any other exit code = wait 30s, retry
#
# For production Linux deployments, prefer the orchestrator's
# restart policy (Docker ``restart: unless-stopped`` or a
# systemd unit with ``Restart=on-failure``) over this bash
# loop. This script exists for bare-metal Linux dev parity
# with the Windows watchdog.
#
# Optional env vars:
#     OPENALGO_ROOT      — project root (auto-detected)
#     OPENALGO_CMD       — runtime command (default: ``uv run app.py``;
#                          set to e.g. ``uv run gunicorn --worker-class
#                          eventlet -w 1 app:app`` for prod)
#     MAX_RETRIES        — default 10
#     RETRY_SLEEP_SECONDS — default 30
# ============================================================
set -uo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
OPENALGO_ROOT="${OPENALGO_ROOT:-$(cd "$SCRIPT_DIR/../.." && pwd)}"
OPENALGO_CMD="${OPENALGO_CMD:-uv run app.py}"
MAX_RETRIES="${MAX_RETRIES:-10}"
RETRY_SLEEP_SECONDS="${RETRY_SLEEP_SECONDS:-30}"

cd "$OPENALGO_ROOT"

child_pid=""
stop_requested=0
forward_signal() {
    local sig="$1"
    if [ -n "$child_pid" ] && kill -0 "$child_pid" 2>/dev/null; then
        echo "[watchdog $(date -Is)] forwarding $sig to openalgo pid=$child_pid"
        kill "-$sig" "$child_pid" || true
    fi
    stop_requested=1
}
trap 'forward_signal TERM' TERM
trap 'forward_signal INT'  INT

RETRIES=0
while true; do
    echo "[watchdog $(date -Is)] launching openalgo retry=$RETRIES (cmd: $OPENALGO_CMD)"
    # shellcheck disable=SC2086
    $OPENALGO_CMD &
    child_pid=$!
    wait "$child_pid" || true
    EC=$?
    child_pid=""
    echo "[watchdog $(date -Is)] openalgo exited code=$EC"

    if [ "$stop_requested" -ne 0 ]; then
        exit "$EC"
    fi

    if [ "$EC" -eq 0 ]; then
        echo "[watchdog $(date -Is)] clean exit; not restarting"
        exit 0
    fi

    RETRIES=$((RETRIES + 1))
    if [ "$RETRIES" -ge "$MAX_RETRIES" ]; then
        echo "[watchdog] ERROR: max restart count ($MAX_RETRIES) reached, giving up" 1>&2
        exit 13
    fi

    echo "[watchdog] restart in ${RETRY_SLEEP_SECONDS}s, allow ports/sockets to clear"
    sleep "$RETRY_SLEEP_SECONDS" &
    sleep_pid=$!
    wait "$sleep_pid" || true
    if [ "$stop_requested" -ne 0 ]; then
        exit 0
    fi
done
