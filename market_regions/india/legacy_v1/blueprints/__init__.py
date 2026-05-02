"""Phase 9-bis-2 final-cleanup — relocated India-only Flask blueprints.

These blueprints register India-shaped UI surfaces (Chartink scraper,
IV/GEX/OI charts on NSE indices, NIFTY/BANKNIFTY straddle UIs, the
Indian sandbox dashboard, India-flavored strategy builder, etc.).
Shim modules at the original ``blueprints.<name>`` path use
``sys.modules`` aliasing to keep ``app.py``'s blueprint registration
imports working without per-callsite changes.
"""
from __future__ import annotations
