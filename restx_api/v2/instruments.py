"""GET /api/v2/instruments/search and /api/v2/instruments/<instrument_id>."""

from __future__ import annotations

import uuid

from flask import request
from flask_restx import Namespace, Resource

from restx_api.v2._auth import error, ok
from utils.logging import get_logger

logger = get_logger(__name__)

api = Namespace("instruments", description="Instrument search and lookup")


@api.route("/search")
class InstrumentSearch(Resource):
    def get(self):
        from database.instruments_repo import instruments_search

        q = request.args.get("q")
        venue_code = request.args.get("venue_code")
        asset_class = request.args.get("asset_class")
        try:
            limit = int(request.args.get("limit", "50"))
            offset = int(request.args.get("offset", "0"))
        except ValueError:
            return error("bad_request", "limit and offset must be integers"), 400
        if limit > 500 or limit <= 0:
            return error("bad_request", "limit must be 1..500"), 400

        rows = instruments_search(
            venue_code=venue_code,
            query=q,
            asset_class=asset_class,
            limit=limit,
            offset=offset,
        )
        return ok([_instrument_to_dict(r) for r in rows]), 200


@api.route("/<string:instrument_id>")
class InstrumentById(Resource):
    def get(self, instrument_id: str):
        from database.instruments_repo import instruments_get_by_id, session_scope
        from database.instruments_repo import InstrumentIdentifier
        from sqlalchemy import select

        try:
            uid = uuid.UUID(instrument_id)
        except ValueError:
            return error("bad_request", f"not a UUID: {instrument_id!r}"), 400

        inst = instruments_get_by_id(uid)
        if inst is None:
            return error("not_found", f"instrument_id={instrument_id} not found"), 404

        with session_scope() as s:
            ids = s.scalars(
                select(InstrumentIdentifier).where(
                    InstrumentIdentifier.instrument_id == uid
                )
            ).all()
            ids_out = [_identifier_to_dict(r) for r in ids]

        return ok({
            "instrument": _instrument_to_dict(inst),
            "identifiers": ids_out,
        }), 200


def _instrument_to_dict(inst) -> dict:
    return {
        "instrument_id": str(inst.instrument_id),
        "venue_code": inst.venue_code,
        "canonical_symbol": inst.canonical_symbol,
        "asset_class": inst.asset_class,
        "instrument_kind": inst.instrument_kind,
        "tick_size": _decimal_or_none(inst.tick_size),
        "lot_size": inst.lot_size,
        "quantity_precision": inst.quantity_precision,
        "min_quantity": _decimal_or_none(inst.min_quantity),
        "underlying_instrument_id": str(inst.underlying_instrument_id)
        if inst.underlying_instrument_id
        else None,
        "expiration_at": inst.expiration_at.isoformat() if inst.expiration_at else None,
        "option_right": inst.option_right,
        "strike": _decimal_or_none(inst.strike),
        "currency": inst.currency,
        "display_name": inst.display_name,
        "is_active": inst.is_active,
    }


def _identifier_to_dict(row) -> dict:
    return {
        "identifier_type": row.identifier_type,
        "identifier_value": row.identifier_value,
        "broker_code": row.broker_code,
        "venue_code": row.venue_code,
    }


def _decimal_or_none(v):
    if v is None:
        return None
    return str(v)
