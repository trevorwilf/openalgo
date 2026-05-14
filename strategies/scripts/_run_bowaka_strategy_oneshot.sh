#!/usr/bin/env bash
# ============================================================
# _run_bowaka_strategy_oneshot.sh
#
# Linux/macOS one-shot launcher for the bowaka strategy daemon.
# Parity with _run_bowaka_strategy_oneshot.cmd, but secrets come
# from the environment rather than being baked into the script
# (the Windows oneshot bakes OPENALGO_API_KEY for convenience —
# do NOT mirror that on Linux/prod; use env or a Docker secret).
#
# Required env vars:
#     OPENALGO_API_KEY         — generated at /apikey
#
# Optional env vars (sensible defaults):
#     HOST_SERVER              — default http://127.0.0.1:5000
#     OPENALGO_STRATEGY_EXCHANGE — default CRYPTO (bypasses the
#                                  /python host's Indian holiday gate)
#     OPENALGO_ROOT            — project root (default: auto-detect)
#     PYTHON_EXE               — interpreter (default:
#                                $OPENALGO_ROOT/.venv/bin/python)
# ============================================================
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
OPENALGO_ROOT="${OPENALGO_ROOT:-$(cd "$SCRIPT_DIR/../.." && pwd)}"
BOWAKA_DIR="$OPENALGO_ROOT/strategies/scripts"

# Cross-platform venv discovery — see run_bowaka_prefilter.sh
# for the rationale.
if [ -z "${PYTHON_EXE:-}" ]; then
    if [ -x "$OPENALGO_ROOT/.venv/bin/python" ]; then
        PYTHON_EXE="$OPENALGO_ROOT/.venv/bin/python"
    elif [ -x "$OPENALGO_ROOT/.venv/Scripts/python.exe" ]; then
        PYTHON_EXE="$OPENALGO_ROOT/.venv/Scripts/python.exe"
    else
        PYTHON_EXE="$OPENALGO_ROOT/.venv/bin/python"
    fi
fi

if [ -z "${OPENALGO_API_KEY:-}" ]; then
    echo "ERROR: OPENALGO_API_KEY must be set in env" 1>&2
    echo "       Generate via the OpenAlgo /apikey page, then" 1>&2
    echo "       export OPENALGO_API_KEY=... before invoking this." 1>&2
    exit 12
fi

export HOST_SERVER="${HOST_SERVER:-http://127.0.0.1:5000}"
export OPENALGO_STRATEGY_EXCHANGE="${OPENALGO_STRATEGY_EXCHANGE:-CRYPTO}"
export PYTHONIOENCODING=utf-8
export PYTHONUTF8=1

cd "$BOWAKA_DIR"
exec "$PYTHON_EXE" bowaka_strategy.py --config bowaka_strategy.yaml
