"""Venue CRUD."""

from __future__ import annotations

from database.instruments_repo import venues_get, venues_list, venues_upsert


def test_upsert_inserts_new_venue(fresh_db) -> None:
    v = venues_upsert(
        "NSE",
        market_family="IN_STOCK",
        timezone_name="Asia/Kolkata",
        base_currency="INR",
        country_code="IN",
        display_name="National Stock Exchange",
    )
    assert v.venue_code == "NSE"
    assert v.timezone_name == "Asia/Kolkata"


def test_upsert_updates_existing_venue(fresh_db) -> None:
    venues_upsert("BSE", market_family="IN_STOCK", timezone_name="Asia/Kolkata")
    updated = venues_upsert(
        "BSE",
        market_family="IN_STOCK",
        timezone_name="Asia/Kolkata",
        display_name="Bombay Stock Exchange",
        metadata={"segment": "cash"},
    )
    assert updated.display_name == "Bombay Stock Exchange"
    assert updated.metadata_json == {"segment": "cash"}


def test_get_returns_none_for_missing(fresh_db) -> None:
    assert venues_get("XYZ") is None


def test_list_filters_by_market_family(fresh_db) -> None:
    venues_upsert("NSE", market_family="IN_STOCK", timezone_name="Asia/Kolkata")
    venues_upsert("XNAS", market_family="US_STOCK", timezone_name="America/New_York")
    venues_upsert("BINANCE", market_family="CRYPTO", timezone_name="UTC")

    indian = venues_list(market_family="IN_STOCK")
    assert [v.venue_code for v in indian] == ["NSE"]

    crypto = venues_list(market_family="CRYPTO")
    assert [v.venue_code for v in crypto] == ["BINANCE"]

    all_venues = venues_list()
    assert {v.venue_code for v in all_venues} == {"NSE", "XNAS", "BINANCE"}
