"""Regression: ``get_broker_name`` must re-check ``is_revoked`` on
every cache hit and key the cache by ``sha256(api_key)`` rather than
the plaintext API key.

Pre-fix behavior:
  * Cache hit short-circuited without consulting the DB. A revoked
    credential kept leaking its broker name for the full 50-minute
    TTL.
  * Cache key was the plaintext API key, putting the credential in
    an in-process dict despite SHA256 being trivial.
"""

from __future__ import annotations

import hashlib

import database.auth_db as auth_db


class _FakeAuth:
    def __init__(self, *, broker: str = "alpaca", revoked: bool = False) -> None:
        self.auth = b"encrypted-token-bytes"
        self.feed_token = None
        self.broker = broker
        self.is_revoked = revoked


class _FakeQuery:
    def __init__(self, sequence: list[_FakeAuth | None]) -> None:
        self._calls = 0
        self._seq = sequence

    def filter_by(self, **_: object) -> "_FakeQuery":
        return self

    def first(self) -> _FakeAuth | None:
        idx = min(self._calls, len(self._seq) - 1)
        self._calls += 1
        return self._seq[idx]


def _patch(monkeypatch, *, sequence: list[_FakeAuth | None]) -> _FakeQuery:
    monkeypatch.setattr(auth_db, "verify_api_key", lambda _k: "alice")
    fake_query = _FakeQuery(sequence)
    monkeypatch.setattr(auth_db.Auth, "query", fake_query)
    auth_db.broker_cache.clear()
    return fake_query


def test_broker_cache_keys_by_sha256_not_plaintext(monkeypatch):
    """The plaintext API key must never appear as a cache key."""
    _patch(monkeypatch, sequence=[_FakeAuth()])

    auth_db.get_broker_name("plain-text-api-key-xyz")

    assert "plain-text-api-key-xyz" not in auth_db.broker_cache
    expected = hashlib.sha256(b"plain-text-api-key-xyz").hexdigest()
    assert expected in auth_db.broker_cache
    assert auth_db.broker_cache[expected] == "alpaca"


def test_broker_cache_rejects_revoked_after_initial_cache(monkeypatch):
    """First call caches the broker. Then the credential is revoked.
    The next call MUST drop the cached entry and return None — pre-fix
    it kept returning ``"alpaca"`` for the rest of the TTL.
    """
    _patch(
        monkeypatch,
        sequence=[
            _FakeAuth(revoked=False),  # first call: valid, populates cache
            _FakeAuth(revoked=True),   # second call: revoked — must purge
        ],
    )

    first = auth_db.get_broker_name("api-key-xyz")
    assert first == "alpaca"
    assert len(auth_db.broker_cache) == 1

    second = auth_db.get_broker_name("api-key-xyz")
    assert second is None
    assert len(auth_db.broker_cache) == 0


def test_broker_cache_returns_cached_when_still_valid(monkeypatch):
    """When the credential is NOT revoked, the cache hit must return
    the cached broker without re-querying repeatedly. (We verify the
    cache hit path runs but does not produce stale data — the second
    call still hits Auth.query for the revocation check, and that's
    intentional defense-in-depth, not a regression.)
    """
    fake_query = _patch(
        monkeypatch,
        sequence=[
            _FakeAuth(revoked=False),
            _FakeAuth(revoked=False),
        ],
    )

    assert auth_db.get_broker_name("api-key-xyz") == "alpaca"
    assert auth_db.get_broker_name("api-key-xyz") == "alpaca"
    # Two calls, two DB queries (one populate + one revocation check).
    # The cache itself stays warm — note the same cache key is reused.
    assert fake_query._calls == 2
    assert len(auth_db.broker_cache) == 1
