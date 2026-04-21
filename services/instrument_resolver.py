"""InstrumentResolver — resolve `InstrumentRef` → `ResolvedInstrument`.

Sits between callers and the two instrument universes:

* the new Phase 2a tables (`instruments`, `broker_instrument_map`,
  `instrument_identifiers`)
* the legacy `symtoken` table accessed via `database.token_db.get_token`

Phase 3a goal is observability + a stable API surface — services that
opt in via ``RESOLVER_V2`` log what the resolver saw while the legacy
path still drives the actual broker API call. Phase 6+ will flip the
authority.

Design notes
------------

* When the instrument is not in the new tables, we fall back to
  `legacy_token_lookup(symbol, venue_code)` and return a
  `ResolvedInstrument(legacy_fallback=True)` with a **synthetic** UUID
  derived from ``uuid5(NAMESPACE_URL, "legacy:{broker}:{venue}:{symbol}")``.
  This gives the rest of the system something stable to key on without
  having to insert into `instruments` on the fly.
* The resolver NEVER writes to the instruments tables. It's a read path.
* Caching: in-process dict with 60s TTL, keyed on ``(ref.to_dict(),
  broker_code)``. Safe to blow away any time via `invalidate()`.
"""

from __future__ import annotations

import threading
import time
import uuid
from dataclasses import dataclass
from typing import Any, Callable, Optional

from domain.enums import IdentifierType
from domain.instrument_ref import InstrumentRef
from utils.logging import get_logger

logger = get_logger(__name__)


# Identifier types that are venue-agnostic. For these, an `external`
# ref can match across venues via `instrument_identifiers`.
_GLOBAL_IDENTIFIER_TYPES = frozenset(
    {
        IdentifierType.ISIN,
        IdentifierType.FIGI,
        IdentifierType.CUSIP,
        IdentifierType.SEDOL,
    }
)


class ResolverMiss(Exception):
    """No instrument matches the ref and no legacy fallback was possible."""


class ResolverAmbiguous(Exception):
    """Multiple equally-scored candidates matched the ref."""


@dataclass(frozen=True)
class ResolvedInstrument:
    """The output of `InstrumentResolver.resolve`.

    `external_token` is the broker-facing token the caller should use
    for the broker API call. When `legacy_fallback=True`, the token
    comes from the legacy `token_db.get_token` and `instrument_id` is a
    synthetic uuid5 (stable across calls but not present in the
    `instruments` table).
    """

    instrument_id: uuid.UUID
    venue_code: str
    canonical_symbol: str
    broker_code: Optional[str] = None
    external_symbol: Optional[str] = None
    external_token: Optional[str] = None
    legacy_fallback: bool = False


class InstrumentResolver:
    """Instance-level resolver with an in-process TTL cache.

    The resolver does not hold database connections — each `resolve`
    call opens a short-lived session via the repo layer's
    `session_scope`. Thread-safe for concurrent reads (the cache uses a
    simple RLock; Python dict ops are atomic for single-key reads).
    """

    def __init__(
        self,
        repo: Any = None,
        legacy_token_lookup: Optional[Callable[[str, str], Any]] = None,
        cache_ttl: float = 60.0,
        logger_: Any = None,
    ) -> None:
        # Late-import the repo so unit tests that inject a fake don't
        # pay the import cost.
        if repo is None:
            from database import instruments_repo as repo
        self._repo = repo

        self._legacy_token_lookup = legacy_token_lookup
        self._cache_ttl = cache_ttl
        self._cache: dict[tuple[Any, ...], tuple[float, ResolvedInstrument]] = {}
        self._cache_lock = threading.RLock()
        self._log = logger_ or logger

    # ------------------------------------------------------------------
    # Public API

    def resolve(
        self, ref: InstrumentRef, broker_code: Optional[str] = None
    ) -> ResolvedInstrument:
        """Resolve `ref` → `ResolvedInstrument`. Raises on miss/ambiguity."""
        cache_key = self._cache_key(ref, broker_code)
        now = time.monotonic()

        with self._cache_lock:
            cached = self._cache.get(cache_key)
            if cached is not None and (now - cached[0]) < self._cache_ttl:
                return cached[1]

        result = self._resolve_uncached(ref, broker_code)

        with self._cache_lock:
            self._cache[cache_key] = (now, result)
        return result

    def resolve_for_quote(
        self, symbol: str, exchange: str, broker_code: str
    ) -> ResolvedInstrument:
        """Convenience wrapper used by services/quotes_service.py."""
        ref = InstrumentRef(venue_code=exchange, canonical_symbol=symbol)
        return self.resolve(ref, broker_code=broker_code)

    def invalidate(self) -> None:
        """Drop every cached entry. Safe to call at any time."""
        with self._cache_lock:
            self._cache.clear()

    # ------------------------------------------------------------------
    # Internals

    @staticmethod
    def _cache_key(ref: InstrumentRef, broker_code: Optional[str]) -> tuple[Any, ...]:
        # model_dump(mode='json') gives a stable JSON-shape that is
        # hashable when converted to a frozenset of items.
        d = ref.model_dump(mode="json")
        return (tuple(sorted(d.items())), broker_code)

    def _resolve_uncached(
        self, ref: InstrumentRef, broker_code: Optional[str]
    ) -> ResolvedInstrument:
        if ref.kind == "id":
            return self._resolve_by_id(ref, broker_code)
        if ref.kind == "venue_symbol":
            return self._resolve_by_venue_symbol(ref, broker_code)
        # external
        return self._resolve_by_external(ref, broker_code)

    # ---- id ------------------------------------------------------------

    def _resolve_by_id(
        self, ref: InstrumentRef, broker_code: Optional[str]
    ) -> ResolvedInstrument:
        assert ref.instrument_id is not None  # kind=='id' guarantee
        inst = self._repo.instruments_get_by_id(ref.instrument_id)
        if inst is None:
            raise ResolverMiss(f"instrument_id={ref.instrument_id} not in universe")

        map_row = None
        if broker_code is not None:
            map_row = self._repo.broker_map_lookup_by_symbol(
                broker_code, inst.venue_code, inst.canonical_symbol
            )

        return ResolvedInstrument(
            instrument_id=inst.instrument_id,
            venue_code=inst.venue_code,
            canonical_symbol=inst.canonical_symbol,
            broker_code=broker_code if map_row is not None else None,
            external_symbol=map_row.external_symbol if map_row else None,
            external_token=map_row.external_token if map_row else None,
            legacy_fallback=False,
        )

    # ---- venue_symbol --------------------------------------------------

    def _resolve_by_venue_symbol(
        self, ref: InstrumentRef, broker_code: Optional[str]
    ) -> ResolvedInstrument:
        assert ref.venue_code is not None and ref.canonical_symbol is not None

        inst = self._repo.instruments_get_by_venue_symbol(
            ref.venue_code, ref.canonical_symbol
        )
        if inst is not None:
            map_row = None
            if broker_code is not None:
                map_row = self._repo.broker_map_lookup_by_symbol(
                    broker_code, ref.venue_code, ref.canonical_symbol
                )
            return ResolvedInstrument(
                instrument_id=inst.instrument_id,
                venue_code=inst.venue_code,
                canonical_symbol=inst.canonical_symbol,
                broker_code=broker_code if map_row is not None else None,
                external_symbol=map_row.external_symbol if map_row else None,
                external_token=map_row.external_token if map_row else None,
                legacy_fallback=False,
            )

        # Legacy fallback path
        if self._legacy_token_lookup is not None and broker_code is not None:
            try:
                token = self._legacy_token_lookup(ref.canonical_symbol, ref.venue_code)
            except Exception as e:
                self._log.warning(
                    "legacy_token_lookup raised for symbol=%s exchange=%s: %s",
                    ref.canonical_symbol, ref.venue_code, e,
                )
                token = None
            if token is not None:
                synthetic_id = uuid.uuid5(
                    uuid.NAMESPACE_URL,
                    f"legacy:{broker_code}:{ref.venue_code}:{ref.canonical_symbol}",
                )
                return ResolvedInstrument(
                    instrument_id=synthetic_id,
                    venue_code=ref.venue_code,
                    canonical_symbol=ref.canonical_symbol,
                    broker_code=broker_code,
                    external_symbol=ref.canonical_symbol,
                    external_token=str(token),
                    legacy_fallback=True,
                )

        raise ResolverMiss(
            f"no instrument for venue_code={ref.venue_code} "
            f"canonical_symbol={ref.canonical_symbol} broker_code={broker_code}"
        )

    # ---- external identifier -------------------------------------------

    def _resolve_by_external(
        self, ref: InstrumentRef, broker_code: Optional[str]
    ) -> ResolvedInstrument:
        assert ref.identifier_type is not None and ref.identifier_value is not None

        ident_type = ref.identifier_type
        ident_value = ref.identifier_value

        # Broker-token / broker-symbol → broker_instrument_map
        if ident_type == IdentifierType.BROKER_TOKEN and broker_code is not None:
            # venue_code is optional on InstrumentRef for external refs; if
            # absent, we'd have to scan all venues. Require it.
            if ref.venue_code is None:
                raise ResolverMiss(
                    "BROKER_TOKEN resolution requires venue_code on the ref"
                )
            map_row = self._repo.broker_map_lookup_by_token(
                broker_code, ref.venue_code, ident_value
            )
            if map_row is None:
                raise ResolverMiss(
                    f"no broker_instrument_map row for broker={broker_code} "
                    f"venue={ref.venue_code} token={ident_value}"
                )
            inst = self._repo.instruments_get_by_id(map_row.instrument_id)
            if inst is None:
                raise ResolverMiss(
                    f"broker_instrument_map row references missing instrument_id="
                    f"{map_row.instrument_id}"
                )
            return ResolvedInstrument(
                instrument_id=inst.instrument_id,
                venue_code=inst.venue_code,
                canonical_symbol=inst.canonical_symbol,
                broker_code=broker_code,
                external_symbol=map_row.external_symbol,
                external_token=map_row.external_token,
                legacy_fallback=False,
            )

        if ident_type == IdentifierType.BROKER_SYMBOL and broker_code is not None:
            if ref.venue_code is None:
                raise ResolverMiss(
                    "BROKER_SYMBOL resolution requires venue_code on the ref"
                )
            map_row = self._repo.broker_map_lookup_by_symbol(
                broker_code, ref.venue_code, ident_value
            )
            if map_row is None:
                raise ResolverMiss(
                    f"no broker_instrument_map row for broker={broker_code} "
                    f"venue={ref.venue_code} symbol={ident_value}"
                )
            inst = self._repo.instruments_get_by_id(map_row.instrument_id)
            if inst is None:
                raise ResolverMiss(
                    f"broker_instrument_map row references missing instrument_id="
                    f"{map_row.instrument_id}"
                )
            return ResolvedInstrument(
                instrument_id=inst.instrument_id,
                venue_code=inst.venue_code,
                canonical_symbol=inst.canonical_symbol,
                broker_code=broker_code,
                external_symbol=map_row.external_symbol,
                external_token=map_row.external_token,
                legacy_fallback=False,
            )

        # Venue-agnostic identifiers (ISIN/FIGI/CUSIP/SEDOL) →
        # instrument_identifiers. broker_code is always None on these rows.
        # If ref.venue_code is set, narrow to that venue; otherwise match
        # any venue_code (direct query; repo.identifier_resolve's
        # _nullable_eq would only match stored NULL rows).
        if ident_type in _GLOBAL_IDENTIFIER_TYPES:
            from sqlalchemy import and_, select
            from database.instruments_repo import InstrumentIdentifier, session_scope

            with session_scope() as s:
                stmt = select(InstrumentIdentifier).where(
                    and_(
                        InstrumentIdentifier.identifier_type == ident_type.value,
                        InstrumentIdentifier.identifier_value == ident_value,
                        InstrumentIdentifier.broker_code.is_(None),
                    )
                )
                if ref.venue_code is not None:
                    stmt = stmt.where(
                        InstrumentIdentifier.venue_code == ref.venue_code
                    )
                matches = list(s.scalars(stmt))

            # Dedupe by instrument_id and filter to active rows.
            seen_ids: set[Any] = set()
            instruments: list[Any] = []
            for m in matches:
                if m.instrument_id in seen_ids:
                    continue
                seen_ids.add(m.instrument_id)
                inst = self._repo.instruments_get_by_id(m.instrument_id)
                if inst is not None:
                    instruments.append(inst)
            if not instruments:
                raise ResolverMiss(
                    f"no instrument for {ident_type.value}={ident_value}"
                )
            if len(instruments) > 1:
                raise ResolverAmbiguous(
                    f"{len(instruments)} instruments match "
                    f"{ident_type.value}={ident_value}; narrow by venue_code"
                )
            inst = instruments[0]
            map_row = None
            if broker_code is not None:
                map_row = self._repo.broker_map_lookup_by_symbol(
                    broker_code, inst.venue_code, inst.canonical_symbol
                )
            return ResolvedInstrument(
                instrument_id=inst.instrument_id,
                venue_code=inst.venue_code,
                canonical_symbol=inst.canonical_symbol,
                broker_code=broker_code if map_row is not None else None,
                external_symbol=map_row.external_symbol if map_row else None,
                external_token=map_row.external_token if map_row else None,
                legacy_fallback=False,
            )

        raise ResolverMiss(
            f"identifier_type={ident_type.value} not supported by resolver "
            f"(broker_code={broker_code})"
        )


# ---------------------------------------------------------------------------
# Default shared instance for the app — lazy so tests that patch
# `database.token_db.get_token` get their patch applied.
# ---------------------------------------------------------------------------

_default_resolver: Optional[InstrumentResolver] = None
_default_lock = threading.RLock()


def get_resolver() -> InstrumentResolver:
    """Return the process-wide default resolver, constructing on first call.

    The default resolver uses `database.token_db.get_token` as its
    legacy fallback.
    """
    global _default_resolver
    with _default_lock:
        if _default_resolver is None:
            from database.token_db import get_token

            _default_resolver = InstrumentResolver(
                legacy_token_lookup=lambda symbol, venue: get_token(symbol, venue),
            )
        return _default_resolver


def reset_default_resolver_for_tests() -> None:
    """Drop the cached default resolver so the next `get_resolver()` call
    rebuilds it. Tests patch `database.token_db.get_token` before calling
    this to make the patch visible through the resolver's lambda.
    """
    global _default_resolver
    with _default_lock:
        _default_resolver = None


__all__ = [
    "InstrumentResolver",
    "ResolvedInstrument",
    "ResolverAmbiguous",
    "ResolverMiss",
    "get_resolver",
    "reset_default_resolver_for_tests",
]
