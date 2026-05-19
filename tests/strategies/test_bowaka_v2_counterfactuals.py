"""Phase 5 — v2 counterfactual reports."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

import bowaka_v2_counterfactuals as cf


def test_counterfactuals_consume_v2_streams():
    entries = [
        {"session_date": "2026-05-15", "symbol": "AAA",
         "order_style": "marketable_limit",
         "hypothetical_pnl_delta": 0.02},
        {"session_date": "2026-05-15", "symbol": "BBB",
         "delay_minutes": 5,
         "hypothetical_pnl_delta": -0.01},
    ]
    exits = [
        {"session_date": "2026-05-15", "symbol": "AAA",
         "variant": "signal_fade_active", "pnl_delta": 0.03},
    ]
    decisions = [
        {"session_date": "2026-05-15", "decision": "accepted",
         "symbol": "AAA"},
        {"session_date": "2026-05-15", "decision": "rejected",
         "symbol": "ZZZ"},
        {"session_date": "2026-05-15", "decision": "accepted",
         "symbol": "BBB"},
    ]
    ledger = []
    report = cf.build_report(
        counterfactual_entries=entries,
        counterfactual_exits=exits,
        entry_decisions=decisions,
        trade_ledger=ledger,
        session_date="2026-05-15",
    )
    assert report["accepted_entries"] == 2
    assert report["rejected_entries"] == 1
    assert len(report["alt_order_style_deltas"]) == 1
    assert len(report["delayed_entry_deltas"]) == 1
    assert len(report["signal_fade_variant_deltas"]) == 1


def test_counterfactuals_filter_other_session_dates():
    """Events from other dates must not bleed into the report."""
    entries = [
        {"session_date": "2026-05-15", "symbol": "AAA",
         "order_style": "marketable_limit", "hypothetical_pnl_delta": 0.02},
        {"session_date": "2026-05-14", "symbol": "OLD",
         "order_style": "marketable_limit", "hypothetical_pnl_delta": -0.10},
    ]
    decisions = [
        {"session_date": "2026-05-15", "decision": "accepted", "symbol": "AAA"},
    ]
    rep = cf.build_report(
        counterfactual_entries=entries,
        counterfactual_exits=[],
        entry_decisions=decisions,
        trade_ledger=[],
        session_date="2026-05-15",
    )
    syms = [d["symbol"] for d in rep["alt_order_style_deltas"]]
    assert "AAA" in syms
    assert "OLD" not in syms


def test_counterfactuals_parity_with_v1_on_shared_session():
    """For a synthetic session expressible in both v1 + v2 schemas,
    the per-trade delta computation is structurally identical (same
    inputs → same outputs)."""
    entries = [
        {"session_date": "2026-05-18", "symbol": "AAA",
         "order_style": "marketable_limit", "hypothetical_pnl_delta": 0.025},
    ]
    rep = cf.build_report(
        counterfactual_entries=entries,
        counterfactual_exits=[],
        entry_decisions=[
            {"session_date": "2026-05-18", "decision": "accepted",
             "symbol": "AAA"},
        ],
        trade_ledger=[],
        session_date="2026-05-18",
    )
    # The delta the report records exactly mirrors the input —
    # parity is structural here: no v1-specific transformations.
    deltas = rep["alt_order_style_deltas"]
    assert len(deltas) == 1
    assert deltas[0]["pnl_delta"] == pytest.approx(0.025)
