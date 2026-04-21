"""Domain error hierarchy."""

from __future__ import annotations

import pytest

from domain.errors import (
    CapabilityMismatch,
    DomainError,
    InstrumentNotResolvable,
    UnsupportedCapability,
    ValidationError,
)


def test_hierarchy() -> None:
    assert issubclass(InstrumentNotResolvable, DomainError)
    assert issubclass(UnsupportedCapability, DomainError)
    assert issubclass(CapabilityMismatch, DomainError)
    assert issubclass(DomainError, Exception)


def test_instrument_not_resolvable_carries_ref() -> None:
    fake_ref = {"venue_code": "NSE", "canonical_symbol": "GHOST"}
    with pytest.raises(InstrumentNotResolvable, match="not in universe") as info:
        raise InstrumentNotResolvable("not in universe", attempted_ref=fake_ref)
    assert info.value.attempted_ref == fake_ref


def test_instrument_not_resolvable_default_ref_none() -> None:
    err = InstrumentNotResolvable("gone")
    assert err.attempted_ref is None


def test_unsupported_capability_message_basic() -> None:
    err = UnsupportedCapability("zerodha", "fractional_shares")
    assert "zerodha" in str(err)
    assert "fractional_shares" in str(err)
    assert err.broker_code == "zerodha"
    assert err.capability_name == "fractional_shares"
    assert err.details is None


def test_unsupported_capability_message_with_details() -> None:
    err = UnsupportedCapability("deltaexchange", "analyzer", details="crypto is 24/7")
    assert "crypto is 24/7" in str(err)
    assert err.details == "crypto is 24/7"


def test_capability_mismatch_is_raisable() -> None:
    with pytest.raises(CapabilityMismatch):
        raise CapabilityMismatch("GTC not allowed on IOC-only venue")


def test_validation_error_is_re_exported_from_pydantic() -> None:
    # Should be the same class pydantic raises.
    import pydantic
    assert ValidationError is pydantic.ValidationError
