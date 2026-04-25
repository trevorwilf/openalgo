"""GET /api/v2/venues — venue catalog from the Phase 4 venue tables.

Reads from ``database/instruments_repo.venues`` (Phase 2a) and
``database/venue_schedule_repo`` (Phase 4). Region plugin metadata is
authoritative for the static surface (timezone, currency, settlement);
the venue table mirrors that into a queryable form so admin UI and
external callers can discover what an instance supports.

Endpoints
---------
* ``GET /api/v2/venues`` — list every seeded venue.
* ``GET /api/v2/venues/<venue_code>`` — one venue.
* ``GET /api/v2/venues/<venue_code>/sessions?date=YYYY-MM-DD`` —
  session windows for that date, computed via
  :mod:`services.venue_session_service`.

Authentication
--------------
Venue metadata is non-sensitive — the routes are open. (The backing
data is the same that the public docs already publish.)
"""

from __future__ import annotations

from datetime import date as date_type, datetime
from typing import Any

from flask import request
from flask_restx import Namespace, Resource

from restx_api.v2._auth import error, ok

api = Namespace("venues", description="Venue catalog (read-only)")


def _venue_to_dict(v) -> dict[str, Any]:
    return {
        "venue_code": v.venue_code,
        "display_name": v.display_name,
        "market_family": v.market_family,
        "country_code": v.country_code,
        "timezone_name": v.timezone_name,
        "base_currency": v.base_currency,
        "settlement_template": v.settlement_type,
        "session_model": v.session_model,
        "metadata": v.metadata_json or {},
    }


@api.route("")
@api.route("/")
class Venues(Resource):
    def get(self):
        from database.instruments_repo import venues_list

        rows = venues_list()
        return ok({"venues": [_venue_to_dict(v) for v in rows]}), 200


@api.route("/<string:venue_code>")
class VenueDetail(Resource):
    def get(self, venue_code: str):
        from database.instruments_repo import venues_get

        v = venues_get(venue_code)
        if v is None:
            return error(
                "venue_not_found",
                f"venue {venue_code!r} not in venues table",
            ), 404
        return ok(_venue_to_dict(v)), 200


@api.route("/<string:venue_code>/sessions")
class VenueSessions(Resource):
    def get(self, venue_code: str):
        from database.instruments_repo import venues_get

        v = venues_get(venue_code)
        if v is None:
            return error(
                "venue_not_found",
                f"venue {venue_code!r} not in venues table",
            ), 404

        date_str = request.args.get("date")
        if date_str:
            try:
                target = datetime.strptime(date_str, "%Y-%m-%d").date()
            except ValueError:
                return error(
                    "bad_request", f"invalid date {date_str!r}; expected YYYY-MM-DD"
                ), 400
        else:
            target = date_type.today()

        from services.venue_session_service import VenueSessionService

        svc = VenueSessionService()
        try:
            windows = svc.session_boundaries_for_date(venue_code, target)
        except Exception as e:  # pragma: no cover - last-resort guard
            return error("internal_error", str(e)), 500

        sessions = [
            {
                "session_type": w.session_type,
                "start_utc": w.start_utc.isoformat(),
                "end_utc": w.end_utc.isoformat(),
                "venue_timezone_name": w.venue_timezone_name,
            }
            for w in windows
        ]
        return ok({
            "venue_code": venue_code,
            "date": target.isoformat(),
            "timezone_name": v.timezone_name,
            "sessions": sessions,
        }), 200
