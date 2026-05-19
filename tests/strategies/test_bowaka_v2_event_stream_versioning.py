"""Phase 6 — event-stream schema-version negotiation."""
from __future__ import annotations

import pytest

import bowaka_v2_event_stream_versioning as v


def test_strategy_rejects_unsupported_schema_version():
    with pytest.raises(v.UnsupportedSchemaError):
        v.assert_supported({"schema_version": 99})


def test_strategy_accepts_current_schema_version():
    v.assert_supported({"schema_version": v.CURRENT_WRITER_VERSION})


def test_is_supported_truthy_for_current_version():
    assert v.is_supported({"schema_version": v.CURRENT_WRITER_VERSION})
    assert not v.is_supported({"schema_version": 99})
