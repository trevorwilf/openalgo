"""Regression: ``get_auth_token_broker`` must not poison ``auth_cache``
with a 24h ``(None, None)`` entry when the looked-up token is revoked
or missing.

Prior behavior: a revoked → restored credential was silently blocked
for the full session-expiry window (up to 24h) by a negative entry in
``auth_cache``.

Fixed behavior: negative results live in a separate short-TTL
``revoked_auth_cache`` (5 minutes). After the short cache expires (or
is cleared) the next lookup re-queries the DB and returns the real
token.
"""

from __future__ import annotations

import database.auth_db as auth_db


class _FakeAuth:
    """Stand-in for the SQLAlchemy ``Auth`` row."""

    def __init__(self, *, broker: str = "alpaca", revoked: bool = False) -> None:
        self.auth = b"encrypted-token-bytes"
        self.feed_token = None
        self.broker = broker
        self.is_revoked = revoked


class _FakeQuery:
    """Stand-in for ``Auth.query`` — controllable per call."""

    def __init__(self, sequence: list[_FakeAuth | None]) -> None:
        self._calls = 0
        self._seq = sequence

    def filter_by(self, **_: object) -> "_FakeQuery":  # noqa: D401 — fluent
        return self

    def first(self) -> _FakeAuth | None:
        idx = min(self._calls, len(self._seq) - 1)
        self._calls += 1
        return self._seq[idx]


def _patch(monkeypatch, *, sequence: list[_FakeAuth | None]) -> _FakeQuery:
    """Wire fake verify + Auth.query so the cache logic runs without DB."""
    monkeypatch.setattr(auth_db, "verify_api_key", lambda _k: "alice")
    monkeypatch.setattr(auth_db, "decrypt_token", lambda _b: "decrypted")
    fake_query = _FakeQuery(sequence)
    monkeypatch.setattr(auth_db.Auth, "query", fake_query)
    auth_db.auth_cache.clear()
    auth_db.revoked_auth_cache.clear()
    return fake_query


def test_revoked_token_does_not_poison_long_lived_auth_cache(monkeypatch):
    _patch(monkeypatch, sequence=[_FakeAuth(revoked=True)])

    result = auth_db.get_auth_token_broker("api-key-xyz")

    assert result == (None, None)
    # The long-lived cache MUST stay clean. Only the short-TTL
    # revoked_auth_cache may carry the negative entry.
    assert len(auth_db.auth_cache) == 0
    assert len(auth_db.revoked_auth_cache) == 1


def test_recovery_returns_real_token_after_negative_cache_expires(monkeypatch):
    """Token revoked, then restored. Once the short-TTL negative cache
    is cleared (simulating the 5-minute TTL expiring), the next call
    must return the restored token — not the previously-cached
    negative result.
    """
    _patch(
        monkeypatch,
        sequence=[
            _FakeAuth(revoked=True),                # first call: revoked
            _FakeAuth(broker="alpaca", revoked=False),  # second call: restored
        ],
    )

    first = auth_db.get_auth_token_broker("api-key-xyz")
    assert first == (None, None)

    # Simulate revoked_auth_cache TTL expiry without waiting 5 minutes.
    auth_db.revoked_auth_cache.clear()

    second = auth_db.get_auth_token_broker("api-key-xyz")
    # Recovery succeeds — pre-fix this returned (None, None) because
    # auth_cache had been poisoned with the negative result.
    assert second == ("decrypted", "alpaca")


def test_revoked_negative_cache_short_circuits_within_ttl(monkeypatch):
    """While the short-TTL negative cache holds, repeated lookups for
    the same revoked key short-circuit without hitting the DB. This
    preserves the original load-shedding intent.
    """
    fake_query = _patch(monkeypatch, sequence=[_FakeAuth(revoked=True)])

    auth_db.get_auth_token_broker("api-key-xyz")
    auth_db.get_auth_token_broker("api-key-xyz")
    auth_db.get_auth_token_broker("api-key-xyz")

    # Only one DB query — subsequent calls were absorbed by the
    # short-TTL revoked_auth_cache.
    assert fake_query._calls == 1
