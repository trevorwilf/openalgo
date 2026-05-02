"""Phase 9-bis-2 final-cleanup — relocated India-only database modules.

SQLAlchemy ORM models + helpers tied to India-shaped data:
Chartink screener results, NSE/BSE quantity-freeze rules, India
market calendar, Historify IST-bound time-series, Indian sandbox
order/position/fund tables, India strategy + flow + leverage state.
Shim modules at the original ``database.<name>`` path preserve
every existing importer.
"""
from __future__ import annotations
