from __future__ import annotations

from utils.security_middleware import SecurityMiddleware, _is_loopback


def test_loopback_detection_covers_ipv4_ipv6_and_mapped_ipv4():
    assert _is_loopback("127.0.0.1") is True
    assert _is_loopback("127.42.0.9") is True
    assert _is_loopback("::1") is True
    assert _is_loopback("::ffff:127.0.0.1") is True
    assert _is_loopback("192.0.2.1") is False
    assert _is_loopback("not-an-ip") is False


def test_loopback_request_skips_ip_ban_database(monkeypatch):
    checked: list[str] = []

    def fake_check(value: str) -> bool:
        checked.append(value)
        return False

    monkeypatch.setattr(
        "utils.security_middleware.IPBan.is_ip_banned", fake_check
    )

    def app(_environ, start_response):
        start_response("200 OK", [("Content-Type", "text/plain")])
        return [b"ok"]

    statuses: list[str] = []
    response = SecurityMiddleware(app)(
        {"REMOTE_ADDR": "127.0.0.1"},
        lambda status, _headers: statuses.append(status),
    )

    assert list(response) == [b"ok"]
    assert statuses == ["200 OK"]
    assert checked == []


def test_remote_request_still_checks_ip_ban_database(monkeypatch):
    checked: list[str] = []

    def fake_check(value: str) -> bool:
        checked.append(value)
        return False

    monkeypatch.setattr(
        "utils.security_middleware.IPBan.is_ip_banned", fake_check
    )
    monkeypatch.setattr("utils.security_middleware.logs_session.remove", lambda: None)

    def app(_environ, start_response):
        start_response("200 OK", [])
        return [b"ok"]

    response = SecurityMiddleware(app)(
        {"REMOTE_ADDR": "192.0.2.10"},
        lambda _status, _headers: None,
    )

    assert list(response) == [b"ok"]
    assert checked == ["192.0.2.10"]
