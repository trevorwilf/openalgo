#!/usr/bin/env bash
# ============================================================
# run_bowaka_prefilter.sh
#
# Linux/macOS equivalent of run_bowaka_prefilter.bat. Reads
# Alpaca credentials from OpenAlgo's .env file and runs the
# Bowaka prefilter. Suitable for invocation from cron (or
# supercronic / yacron in a container).
#
# Expected .env keys (priority order, first match wins):
#     ALPACA_API_KEY_ID      / ALPACA_API_SECRET_KEY
#     ALPACA_API_KEY         / ALPACA_API_SECRET
#     BROKER_API_KEY         / BROKER_API_SECRET
#
# If your OpenAlgo install uses BROKER_API_KEY for a non-Alpaca
# broker, add an explicit ALPACA_API_KEY / ALPACA_API_SECRET
# pair to your .env to disambiguate.
#
# Environment overrides (any can be preset before invocation):
#     OPENALGO_ROOT   — project root (default: auto-detected)
#     ENV_FILE        — path to .env (default: $OPENALGO_ROOT/.env)
#     PYTHON_EXE      — python interpreter (default: $OPENALGO_ROOT/.venv/bin/python)
# ============================================================
set -euo pipefail

# === Paths ===
# Resolve project root from this script's location:
#   strategies/scripts/run_bowaka_prefilter.sh → project root
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
OPENALGO_ROOT="${OPENALGO_ROOT:-$(cd "$SCRIPT_DIR/../.." && pwd)}"
ENV_FILE="${ENV_FILE:-$OPENALGO_ROOT/.env}"
BOWAKA_DIR="$OPENALGO_ROOT/strategies/scripts"

# Python interpreter resolution. Cross-platform: Linux/macOS venvs use
# ``.venv/bin/python``; Windows venvs use ``.venv/Scripts/python.exe``.
# The .sh wrappers stay usable from Git Bash / WSL on a Windows dev
# machine by falling through both.
if [ -z "${PYTHON_EXE:-}" ]; then
    if [ -x "$OPENALGO_ROOT/.venv/bin/python" ]; then
        PYTHON_EXE="$OPENALGO_ROOT/.venv/bin/python"
    elif [ -x "$OPENALGO_ROOT/.venv/Scripts/python.exe" ]; then
        PYTHON_EXE="$OPENALGO_ROOT/.venv/Scripts/python.exe"
    else
        PYTHON_EXE="$OPENALGO_ROOT/.venv/bin/python"   # fall through to the
                                                       # error message below
    fi
fi

# === Sanity checks ===
if [ ! -f "$ENV_FILE" ]; then
    echo "ERROR: .env not found at $ENV_FILE" 1>&2
    exit 11
fi
if [ ! -x "$PYTHON_EXE" ]; then
    echo "ERROR: python not found at $PYTHON_EXE" 1>&2
    echo "       Run \`uv sync\` from $OPENALGO_ROOT to create the venv," 1>&2
    echo "       or set PYTHON_EXE to an absolute interpreter path." 1>&2
    exit 10
fi
if [ ! -f "$BOWAKA_DIR/bowaka_prefilter.py" ]; then
    echo "ERROR: bowaka_prefilter.py not found at $BOWAKA_DIR" 1>&2
    exit 11
fi

# === Parse .env for Alpaca credentials ===
# Fallback cascade matches run_bowaka_prefilter.bat: try the
# most-specific key first, fall back through legacy aliases.
# Each grep returns the value AFTER `=` for a top-level KEY=VAL
# line (commented lines and indented assignments are ignored).
extract_env_value() {
    local key="$1"
    # Match lines starting with optional whitespace, the key, optional
    # whitespace, =, optional whitespace, optional matching quotes,
    # then capture the rest. Strip trailing whitespace + matching quote.
    grep -E "^[[:space:]]*${key}[[:space:]]*=" "$ENV_FILE" \
        | head -n1 \
        | sed -E "s/^[[:space:]]*${key}[[:space:]]*=[[:space:]]*//; s/[[:space:]]*$//; s/^'(.*)'$/\\1/; s/^\"(.*)\"\$/\\1/" \
        || true
}

ALPACA_API_KEY_ID="${ALPACA_API_KEY_ID:-$(extract_env_value ALPACA_API_KEY_ID)}"
[ -n "$ALPACA_API_KEY_ID" ] || ALPACA_API_KEY_ID="$(extract_env_value ALPACA_API_KEY)"
[ -n "$ALPACA_API_KEY_ID" ] || ALPACA_API_KEY_ID="$(extract_env_value BROKER_API_KEY)"

ALPACA_API_SECRET_KEY="${ALPACA_API_SECRET_KEY:-$(extract_env_value ALPACA_API_SECRET_KEY)}"
[ -n "$ALPACA_API_SECRET_KEY" ] || ALPACA_API_SECRET_KEY="$(extract_env_value ALPACA_API_SECRET)"
[ -n "$ALPACA_API_SECRET_KEY" ] || ALPACA_API_SECRET_KEY="$(extract_env_value BROKER_API_SECRET)"

if [ -z "$ALPACA_API_KEY_ID" ]; then
    echo "ERROR: No Alpaca API key found in $ENV_FILE" 1>&2
    echo "Looked for: ALPACA_API_KEY_ID, ALPACA_API_KEY, BROKER_API_KEY" 1>&2
    exit 12
fi
if [ -z "$ALPACA_API_SECRET_KEY" ]; then
    echo "ERROR: No Alpaca API secret found in $ENV_FILE" 1>&2
    echo "Looked for: ALPACA_API_SECRET_KEY, ALPACA_API_SECRET, BROKER_API_SECRET" 1>&2
    exit 13
fi

# Mask key for logging — show first 4 chars only
echo "Loaded Alpaca credentials from .env (key starts with ${ALPACA_API_KEY_ID:0:4}...)"

# === Run ===
# Force UTF-8 on stdout so log messages with non-ASCII characters
# (em-dashes, arrows, currency symbols) flow cleanly through any
# locale (Docker containers default to C/POSIX which strips UTF-8).
export PYTHONIOENCODING=utf-8
export PYTHONUTF8=1
export ALPACA_API_KEY_ID
export ALPACA_API_SECRET_KEY

cd "$BOWAKA_DIR"
exec "$PYTHON_EXE" bowaka_prefilter.py --config bowaka_prefilter.yaml
