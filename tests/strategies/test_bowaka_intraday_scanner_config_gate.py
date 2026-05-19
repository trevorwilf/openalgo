"""Phase 3 — scanner startup config gate tests."""
from __future__ import annotations

import logging

import pytest

import bowaka_intraday_scanner as scanner


def test_scanner_refuses_non_sip_when_research_flag_off():
    cfg = {
        "data": {"feed": "iex", "allow_non_sip_for_research_only": False},
    }
    with pytest.raises(scanner.ConfigError):
        scanner.validate_startup_config(cfg)


def test_scanner_emits_iex_warning_at_startup(caplog):
    cfg = {
        "data": {"feed": "iex", "allow_non_sip_for_research_only": True},
    }
    with caplog.at_level(logging.WARNING, logger="bowaka_intraday_scanner"):
        scanner.validate_startup_config(cfg)
    msg = " ".join(r.getMessage() for r in caplog.records)
    assert "iex" in msg.lower() or "partial-tape" in msg.lower()


def test_scanner_accepts_sip():
    cfg = {
        "data": {"feed": "sip", "allow_non_sip_for_research_only": False},
    }
    # Must not raise.
    scanner.validate_startup_config(cfg)
