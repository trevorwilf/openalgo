"""InstrumentRef `exactly one of` constraint and accessors."""

from __future__ import annotations

from uuid import UUID, uuid4

import pytest
from pydantic import ValidationError

from domain.enums import IdentifierType
from domain.instrument_ref import InstrumentRef


def test_shape_id() -> None:
    ref = InstrumentRef(instrument_id=uuid4())
    assert ref.kind == "id"
    d = ref.to_dict()
    assert "instrument_id" in d
    assert "venue_code" not in d


def test_shape_venue_symbol() -> None:
    ref = InstrumentRef(venue_code="NSE", canonical_symbol="RELIANCE")
    assert ref.kind == "venue_symbol"
    d = ref.to_dict()
    assert d == {"venue_code": "NSE", "canonical_symbol": "RELIANCE"}


def test_shape_external_isin() -> None:
    ref = InstrumentRef(
        identifier_type=IdentifierType.ISIN,
        identifier_value="INE002A01018",
    )
    assert ref.kind == "external"
    d = ref.to_dict()
    assert d == {"identifier_type": "ISIN", "identifier_value": "INE002A01018"}


def test_shape_external_with_broker_and_venue() -> None:
    ref = InstrumentRef(
        identifier_type=IdentifierType.BROKER_TOKEN,
        identifier_value="99999",
        broker_code="zerodha",
    )
    assert ref.kind == "external"


def test_empty_ref_raises() -> None:
    with pytest.raises(ValidationError, match="requires exactly one"):
        InstrumentRef()


def test_two_shapes_set_raises() -> None:
    with pytest.raises(ValidationError, match="exactly one"):
        InstrumentRef(
            instrument_id=uuid4(),
            venue_code="NSE",
            canonical_symbol="RELIANCE",
        )


def test_partial_venue_symbol_raises_missing_symbol() -> None:
    with pytest.raises(ValidationError, match=r"(canonical_symbol|requires exactly one)"):
        InstrumentRef(venue_code="NSE")


def test_partial_venue_symbol_raises_missing_venue() -> None:
    with pytest.raises(ValidationError, match=r"(venue_code|requires exactly one)"):
        InstrumentRef(canonical_symbol="RELIANCE")


def test_partial_identifier_raises_missing_value() -> None:
    with pytest.raises(ValidationError, match=r"(identifier_value|requires exactly one)"):
        InstrumentRef(identifier_type=IdentifierType.ISIN)


def test_partial_identifier_raises_missing_type() -> None:
    with pytest.raises(ValidationError, match=r"(identifier_type|requires exactly one)"):
        InstrumentRef(identifier_value="INE002A01018")


def test_frozen() -> None:
    ref = InstrumentRef(venue_code="NSE", canonical_symbol="SBIN")
    with pytest.raises(Exception):
        ref.venue_code = "BSE"  # type: ignore[misc]


def test_to_dict_for_id_shape_renders_uuid_string() -> None:
    uid = UUID("12345678-1234-5678-1234-567812345678")
    ref = InstrumentRef(instrument_id=uid)
    d = ref.to_dict()
    assert d["instrument_id"] == str(uid)
