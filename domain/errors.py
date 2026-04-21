"""Domain-level exception hierarchy.

Keep these narrow — the point is to let callers distinguish "this
broker cannot do that" (UnsupportedCapability) from "the instrument
does not exist" (InstrumentNotResolvable) from "the request is
malformed" (ValidationError, re-exported from pydantic).
"""

from __future__ import annotations

from typing import Any

from pydantic import ValidationError  # re-exported


class DomainError(Exception):
    """Base for all intentional domain-layer errors."""


class InstrumentNotResolvable(DomainError):
    """The requested instrument cannot be resolved in the current universe.

    Carries the attempted `InstrumentRef` for logging. Stored as
    `attempted_ref` attribute since importing the type here would
    create a circular import.
    """

    def __init__(self, message: str, attempted_ref: Any | None = None) -> None:
        super().__init__(message)
        self.attempted_ref = attempted_ref


class UnsupportedCapability(DomainError):
    """The active broker does not expose the capability this operation needs.

    Example: a crypto-only broker being asked for an Indian-style MIS
    product. `broker_code`, `capability_name`, and `details` are for
    structured logging.
    """

    def __init__(
        self,
        broker_code: str,
        capability_name: str,
        details: str | None = None,
    ) -> None:
        msg = f"broker {broker_code!r} does not support capability {capability_name!r}"
        if details:
            msg = f"{msg}: {details}"
        super().__init__(msg)
        self.broker_code = broker_code
        self.capability_name = capability_name
        self.details = details


class CapabilityMismatch(DomainError):
    """A request combines capabilities in a way the active broker does not allow.

    Distinct from UnsupportedCapability: each piece alone may be supported,
    but the combination is not (e.g., GTC on an IOC-only venue).
    """


__all__ = [
    "CapabilityMismatch",
    "DomainError",
    "InstrumentNotResolvable",
    "UnsupportedCapability",
    "ValidationError",
]
