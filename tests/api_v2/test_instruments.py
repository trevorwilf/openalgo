"""GET /api/v2/instruments/{search,<id>} contract tests."""

from __future__ import annotations


def _seed_instrument(venue: str = "NSE", symbol: str = "RELIANCE"):
    from database.instruments_repo import instruments_create, venues_upsert

    venues_upsert(venue, market_family="IN_STOCK", timezone_name="Asia/Kolkata")
    return instruments_create(
        venue_code=venue,
        canonical_symbol=symbol,
        asset_class="EQUITY",
        instrument_kind="CASH",
    )


def test_search_returns_matching_rows(client, flask_app) -> None:
    _seed_instrument("NSE", "RELIANCE")
    _seed_instrument("NSE", "INFY")
    _seed_instrument("BSE", "SBIN")

    resp = client.get("/api/v2/instruments/search?q=REL&venue_code=NSE")
    assert resp.status_code == 200
    rows = resp.get_json()["data"]
    assert len(rows) == 1
    assert rows[0]["canonical_symbol"] == "RELIANCE"


def test_search_validates_limit(client) -> None:
    resp = client.get("/api/v2/instruments/search?limit=9999")
    assert resp.status_code == 400
    assert resp.get_json()["error"]["code"] == "bad_request"


def test_search_validates_int_params(client) -> None:
    resp = client.get("/api/v2/instruments/search?limit=nope")
    assert resp.status_code == 400


def test_by_id_hit(client, flask_app) -> None:
    from database.instruments_repo import identifier_add

    inst = _seed_instrument("NSE", "TCS")
    identifier_add(inst.instrument_id, "ISIN", "INE467B01029", venue_code="NSE")

    resp = client.get(f"/api/v2/instruments/{inst.instrument_id}")
    assert resp.status_code == 200
    body = resp.get_json()["data"]
    assert body["instrument"]["canonical_symbol"] == "TCS"
    idents = body["identifiers"]
    assert any(i["identifier_type"] == "ISIN" for i in idents)


def test_by_id_miss(client) -> None:
    import uuid

    resp = client.get(f"/api/v2/instruments/{uuid.uuid4()}")
    assert resp.status_code == 404
    assert resp.get_json()["error"]["code"] == "not_found"


def test_by_id_invalid_uuid(client) -> None:
    resp = client.get("/api/v2/instruments/not-a-uuid")
    assert resp.status_code == 400
    assert resp.get_json()["error"]["code"] == "bad_request"
