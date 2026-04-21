"""InstrumentRef — a resolvable pointer to an instrument.

Exactly ONE of these shapes must be set:

1. `instrument_id` — canonical internal UUID (the preferred form once
   Phase 2a's instruments table is populated).
2. `venue_code` + `canonical_symbol` — human-written form still common
   in user-facing APIs and backward-compatible paths.
3. `identifier_type` + `identifier_value` (+ optional `broker_code`,
   `venue_code`) — external identifier like ISIN, FIGI, or a
   broker-specific token.

This three-way constraint is enforced by a model validator.
"""

from __future__ import annotations

from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, model_validator

from domain.enums import IdentifierType

RefKind = Literal["id", "venue_symbol", "external"]


class InstrumentRef(BaseModel):
    """Resolvable pointer to an instrument.

    Prefer `instrument_id` for internal code paths; the other shapes
    exist for external-boundary compatibility (user input, broker-
    callback payloads, legacy v1 responses).
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    # Shape 1: canonical UUID
    instrument_id: UUID | None = None

    # Shape 2: (venue_code, canonical_symbol)
    venue_code: str | None = None
    canonical_symbol: str | None = None

    # Shape 3: (identifier_type, identifier_value, ...)
    identifier_type: IdentifierType | None = None
    identifier_value: str | None = None

    # Optional context for shapes 2 & 3
    broker_code: str | None = None

    @model_validator(mode="after")
    def _exactly_one_shape(self) -> InstrumentRef:
        has_id = self.instrument_id is not None
        has_venue_symbol = self.venue_code is not None and self.canonical_symbol is not None
        has_external = self.identifier_type is not None and self.identifier_value is not None

        active = sum((has_id, has_venue_symbol, has_external))

        # Multiple full shapes → error. A bare venue_code alongside an
        # external ref is allowed (narrowing context), but venue+symbol
        # both set alongside another shape is not.
        if active > 1:
            raise ValueError(
                "InstrumentRef accepts exactly one of: "
                "(instrument_id) | (venue_code + canonical_symbol) | "
                "(identifier_type + identifier_value) — got multiple"
            )

        # Identifier half-set is always an error (the pair is atomic).
        if self.identifier_type is not None and self.identifier_value is None:
            raise ValueError("identifier_type set without identifier_value")
        if self.identifier_value is not None and self.identifier_type is None:
            raise ValueError("identifier_value set without identifier_type")

        # venue/symbol half-set is only an error when NOT attached to an
        # external ref as optional narrowing context.
        if not has_external:
            if self.venue_code is not None and self.canonical_symbol is None:
                raise ValueError("venue_code set without canonical_symbol")
            if self.canonical_symbol is not None and self.venue_code is None:
                raise ValueError("canonical_symbol set without venue_code")

        if active == 0:
            raise ValueError(
                "InstrumentRef requires exactly one of: "
                "(instrument_id) | (venue_code + canonical_symbol) | "
                "(identifier_type + identifier_value)"
            )
        return self

    @property
    def kind(self) -> RefKind:
        if self.instrument_id is not None:
            return "id"
        if self.venue_code is not None and self.canonical_symbol is not None:
            return "venue_symbol"
        # Model-validator guarantees one of three shapes is set, so this
        # branch is external.
        return "external"

    def to_dict(self) -> dict[str, Any]:
        """Logging-friendly dict. Omits None fields. UUIDs rendered as str."""
        data = self.model_dump(mode="json")
        return {k: v for k, v in data.items() if v is not None}


__all__ = ["InstrumentRef", "RefKind"]
