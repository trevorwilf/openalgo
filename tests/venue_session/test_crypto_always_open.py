"""CRYPTO / DELTA_EXCHANGE — always open, 24/7."""

from __future__ import annotations

from datetime import date, datetime, timezone


def test_crypto_open_on_sunday_midnight(service) -> None:
    at = datetime(2026, 4, 19, 0, 0, tzinfo=timezone.utc)
    assert service.is_open("CRYPTO", at) is True


def test_crypto_open_on_weekday_afternoon(service) -> None:
    at = datetime(2026, 4, 21, 14, 30, tzinfo=timezone.utc)
    assert service.is_open("CRYPTO", at) is True


def test_crypto_session_boundaries_on_weekend(service) -> None:
    windows = service.session_boundaries_for_date("CRYPTO", date(2026, 4, 19))
    assert len(windows) == 1
    assert windows[0].session_type == "ALL_DAY"


def test_delta_exchange_open_always(service) -> None:
    at = datetime(2026, 4, 19, 3, 0, tzinfo=timezone.utc)
    assert service.is_open("DELTA_EXCHANGE", at) is True


def test_crypto_trading_days_whole_week(service) -> None:
    days = service.trading_days_in_range(
        "CRYPTO", date(2026, 4, 19), date(2026, 4, 25)
    )
    assert len(days) == 7
