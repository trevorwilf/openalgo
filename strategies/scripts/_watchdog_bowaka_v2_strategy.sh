#!/usr/bin/env bash
# Linux mirror of _watchdog_bowaka_v2_strategy.cmd. Restart-loops the
# v2 consumer. Exit codes 0, 5, 99 are clean shutdown; anything else
# triggers a 30s-backoff restart, capped at 10 retries per launch.

set -uo pipefail

ROOT="${BOWAKA_ROOT:-/opt/bowaka}"
PY="${PY:-$ROOT/.venv/bin/python}"
test -x "$PY" || PY="$(command -v python3)"
CFG="${BOWAKA_V2_CFG:-$ROOT/strategies/scripts/bowaka_v2_config.yaml}"

if [ -z "${OPENALGO_API_KEY:-}" ]; then
    echo "[watchdog] ERROR: OPENALGO_API_KEY must be set" >&2
    exit 12
fi
: "${HOST_SERVER:=http://127.0.0.1:5000}"
: "${OPENALGO_STRATEGY_EXCHANGE:=CRYPTO}"
export PYTHONIOENCODING=utf-8 PYTHONUTF8=1 HOST_SERVER OPENALGO_STRATEGY_EXCHANGE

cd "$ROOT"

retries=0
max_retries=10

while :; do
    echo "[watchdog $(date -Iseconds)] launching bowaka_v2_strategy retry=$retries"
    "$PY" strategies/scripts/bowaka_v2_strategy.py --config "$CFG"
    ec=$?
    echo "[watchdog $(date -Iseconds)] bowaka_v2 exited code=$ec"
    case "$ec" in
        0|5|99) echo "[watchdog] final-code=$ec"; exit "$ec" ;;
    esac
    retries=$((retries + 1))
    if [ "$retries" -ge "$max_retries" ]; then
        echo "[watchdog] ERROR: max restart count reached" >&2
        exit 13
    fi
    echo "[watchdog] restart in 30s"
    sleep 30
done
