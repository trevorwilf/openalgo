#!/usr/bin/env python3
"""Bowaka v2 — event-stream schema-version negotiation.

When the scanner emits ``schema_version: 3`` but the strategy is
built expecting schema 4 (future), the strategy must refuse to read
the stream with a clear error rather than silently mis-interpreting
fields. This module bakes in the version-compatibility table.
"""
from __future__ import annotations

import bowaka_v2_schemas as schemas


# Supported schema versions, oldest -> newest. The current writer
# emits the LAST element of this tuple. Readers may accept anything
# in this set.
SUPPORTED_SCHEMA_VERSIONS: tuple[int, ...] = (3,)

CURRENT_WRITER_VERSION: int = schemas.CANDIDATE_EVENT_SCHEMA_VERSION  # = 3


class UnsupportedSchemaError(RuntimeError):
    pass


def assert_supported(ev: dict) -> None:
    """Raise UnsupportedSchemaError when the event's
    schema_version is not in SUPPORTED_SCHEMA_VERSIONS."""
    v = ev.get("schema_version")
    if v not in SUPPORTED_SCHEMA_VERSIONS:
        raise UnsupportedSchemaError(
            f"event schema_version={v!r} not in supported set "
            f"{SUPPORTED_SCHEMA_VERSIONS}"
        )


def is_supported(ev: dict) -> bool:
    return ev.get("schema_version") in SUPPORTED_SCHEMA_VERSIONS
