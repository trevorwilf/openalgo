#!/usr/bin/env bash
# ============================================================
# _watchdog_bowaka_strategy.sh
#
# Linux/macOS equivalent of _watchdog_bowaka_strategy.cmd.
# Wraps the strategy in a restart loop so an unexpected crash
# (network blip, transient broker error, etc.) doesn't leave
# the user without coverage during the session.
#
# Exit codes that DO NOT trigger a restart:
#     0  = clean shutdown (SIGINT / SIGTERM)
#     5  = handshake mismatch (config drift; needs operator fix)
#     99 = L3 hard-kill flag dropped (operator intent)
#
# Any other exit code = wait 30s, retry. Caps at 10 restarts
# per launch — past that, give up so a config-broken script
# doesn't infinite-loop.
#
# Required env vars:
#     OPENALGO_API_KEY
#
# Optional env vars:
#     HOST_SERVER                — default http://127.0.0.1:5000
#     OPENALGO_STRATEGY_EXCHANGE — default CRYPTO
#     OPENALGO_ROOT              — auto-detected
#     PYTHON_EXE                 — auto-detected from $OPENALGO_ROOT/.venv
#     MAX_RETRIES                — default 10
#     RETRY_SLEEP_SECONDS        — default 30
#
# For Docker / systemd, prefer the orchestrator's restart policy
# (``restart: unless-stopped`` / ``Restart=on-failure``) over this
# bash loop — same retry semantics, with better signal handling
# and log capture. This script exists for bare-metal Linux dev
# parity with the Windows watchdog.
# ============================================================
set -uo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
OPENALGO_ROOT="${OPENALGO_ROOT:-$(cd "$SCRIPT_DIR/../.." && pwd)}"
BOWAKA_DIR="$OPENALGO_ROOT/strategies/scripts"

# Cross-platform venv discovery — see run_bowaka_prefilter.sh.
if [ -z "${PYTHON_EXE:-}" ]; then
    if [ -x "$OPENALGO_ROOT/.venv/bin/python" ]; then
        PYTHON_EXE="$OPENALGO_ROOT/.venv/bin/python"
    elif [ -x "$OPENALGO_ROOT/.venv/Scripts/python.exe" ]; then
        PYTHON_EXE="$OPENALGO_ROOT/.venv/Scripts/python.exe"
    else
        PYTHON_EXE="$OPENALGO_ROOT/.venv/bin/python"
    fi
fi

MAX_RETRIES="${MAX_RETRIES:-10}"
RETRY_SLEEP_SECONDS="${RETRY_SLEEP_SECONDS:-30}"

if [ ! -x "$PYTHON_EXE" ]; then
    echo "[watchdog] ERROR: python not found at $PYTHON_EXE" 1>&2
    exit 10
fi
if [ ! -f "$BOWAKA_DIR/bowaka_strategy.py" ]; then
    echo "[watchdog] ERROR: bowaka_strategy.py not found" 1>&2
    exit 11
fi
if [ -z "${OPENALGO_API_KEY:-}" ]; then
    echo "[watchdog] ERROR: OPENALGO_API_KEY must be set" 1>&2
    exit 12
fi

export HOST_SERVER="${HOST_SERVER:-http://127.0.0.1:5000}"
export OPENALGO_STRATEGY_EXCHANGE="${OPENALGO_STRATEGY_EXCHANGE:-CRYPTO}"
export PYTHONIOENCODING=utf-8
export PYTHONUTF8=1

cd "$BOWAKA_DIR"

# Track child PID so SIGTERM / SIGINT from the orchestrator
# propagates cleanly down to the python process (bowaka has its
# own signal handler that drains the loop before exit).
child_pid=""
forward_signal() {
    local sig="$1"
    if [ -n "$child_pid" ] && kill -0 "$child_pid" 2>/dev/null; then
        echo "[watchdog $(date -Is)] forwarding $sig to bowaka pid=$child_pid"
        kill "-$sig" "$child_pid" || true
    fi
    # Mark we received a stop signal; the retry loop will exit
    # after the current child terminates.
    stop_requested=1
}
stop_requested=0
trap 'forward_signal TERM' TERM
trap 'forward_signal INT'  INT

RETRIES=0
while true; do
    echo "[watchdog $(date -Is)] launching bowaka_strategy retry=$RETRIES"
    "$PYTHON_EXE" bowaka_strategy.py --config bowaka_strategy.yaml &
    child_pid=$!
    wait "$child_pid" || true
    EC=$?
    child_pid=""
    echo "[watchdog $(date -Is)] bowaka exited code=$EC"

    # Stop signal received: exit with the child's code regardless of
    # the usual retry rules.
    if [ "$stop_requested" -ne 0 ]; then
        exit "$EC"
    fi

    case "$EC" in
        0|5|99)
            echo "[watchdog $(date -Is)] watchdog exiting cleanly final-code=$EC"
            exit "$EC"
            ;;
    esac

    RETRIES=$((RETRIES + 1))
    if [ "$RETRIES" -ge "$MAX_RETRIES" ]; then
        echo "[watchdog] ERROR: max restart count ($MAX_RETRIES) reached, giving up" 1>&2
        exit 13
    fi

    echo "[watchdog] restart in ${RETRY_SLEEP_SECONDS}s"
    sleep "$RETRY_SLEEP_SECONDS" &
    sleep_pid=$!
    wait "$sleep_pid" || true
    if [ "$stop_requested" -ne 0 ]; then
        echo "[watchdog $(date -Is)] stop requested during sleep; exiting"
        exit 0
    fi
done
