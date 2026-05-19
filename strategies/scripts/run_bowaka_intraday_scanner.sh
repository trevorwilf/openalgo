#!/usr/bin/env bash
# Bowaka v2 intraday scanner wrapper.
set -euo pipefail
cd "$(dirname "$0")/../.."
PY="${PY:-./.venv/bin/python}"
test -x "$PY" || PY="$(command -v python3)"
CFG="${BOWAKA_V2_CFG:-strategies/scripts/bowaka_v2_config.yaml}"
"$PY" strategies/scripts/bowaka_intraday_scanner.py --config "$CFG" "$@"
