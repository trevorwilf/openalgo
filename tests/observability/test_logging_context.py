"""log_context — nested contexts merge, exit restores prior state."""

from __future__ import annotations

from utils.logging_context import current_context, log_context


def test_context_merge_and_restore():
    assert current_context() == {}
    with log_context(broker_code="alpaca"):
        assert current_context()["broker_code"] == "alpaca"
        with log_context(venue_code="XNAS"):
            ctx = current_context()
            assert ctx["broker_code"] == "alpaca"
            assert ctx["venue_code"] == "XNAS"
        assert "venue_code" not in current_context()
    assert current_context() == {}


def test_context_filters_none_fields():
    with log_context(broker_code="alpaca", venue_code=None):
        assert current_context() == {"broker_code": "alpaca"}


def test_context_boolean_fields_carried():
    with log_context(legacy_fallback=True):
        assert current_context()["legacy_fallback"] is True
