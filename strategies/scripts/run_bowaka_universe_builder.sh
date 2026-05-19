#!/usr/bin/env bash
# Bowaka v2 universe builder wrapper. Mirrors the v1
# run_bowaka_prefilter.sh shape so operators have a 1:1 swap.
set -euo pipefail

cd "$(dirname "$0")/.."
PY="${PY:-./.venv/bin/python}"
test -x "$PY" || PY="$(command -v python3)"

CFG="${BOWAKA_V2_UNIVERSE_CFG:-strategies/scripts/bowaka_universe_builder.yaml}"

"$PY" strategies/scripts/bowaka_universe_builder.py --config "$CFG" "$@"
