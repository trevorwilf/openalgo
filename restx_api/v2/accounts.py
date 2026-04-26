"""GET /api/v2/positions and /api/v2/balances.

Two separate flask-restx namespaces so each lives directly under
``/api/v2/`` rather than a shared ``accounts/`` prefix.

Phase 5 v4 (ADR 0023, invariant 5) — fail-closed dispatch matrix:

* Active broker resolves to **India** (``supported_regions`` includes
  ``"india"``): proxy to the legacy India services
  (``services.positions_service.get_positions_with_auth``,
  ``services.funds_service.get_funds_with_auth``). Bit-identical for
  India.
* Active broker is **non-India** AND a
  :class:`BrokerPositionAdapter` /
  :class:`BrokerBalanceAdapter` is registered: dispatch through the
  adapter and return the normalized payload.
* Active broker is **non-India** AND no adapter is registered: return
  HTTP 503 with code
  ``promoted_capability_unavailable`` and sub-code
  ``position_adapter_not_registered`` /
  ``balance_adapter_not_registered`` per the v4 error taxonomy.
"""

from __future__ import annotations

from typing import Any

from flask_restx import Namespace, Resource

from domain.errors import ErrorCode
from restx_api.v2._auth import error, ok, resolve_auth
from utils.logging import get_logger

logger = get_logger(__name__)

positions_api = Namespace("positions", description="Normalized position view")
balances_api = Namespace("balances", description="Normalized balance view")


def _broker_is_india(broker: str | None) -> bool:
    """``True`` when the active broker's plugin declares India region
    OR has no explicit ``supported_regions`` (legacy India plugin shape)."""
    if not broker:
        return True
    try:
        from utils.plugin_loader import get_broker_capabilities

        caps = get_broker_capabilities(broker)
    except Exception:
        return True
    if caps is None:
        return True
    regions = list(getattr(caps, "supported_regions", None) or [])
    if not regions:
        return True
    return any(str(r).strip().lower() == "india" for r in regions)


def _account_ctx(broker: str | None, auth_token: str | None) -> dict[str, Any]:
    return {
        "broker_code": broker,
        "auth_token": auth_token,
    }


@positions_api.route("")
@positions_api.route("/")
class Positions(Resource):
    def get(self):
        auth_token, broker, auth_err = resolve_auth()
        if auth_err is not None:
            return error("unauthorized", auth_err), 401

        # Promoted-lane adapter dispatch first.
        from services.broker_market_data_registry import (
            get_broker_position_adapter,
        )

        adapter = get_broker_position_adapter(broker or "")
        if adapter is not None:
            try:
                positions = adapter.get_positions(_account_ctx(broker, auth_token))
            except Exception as e:
                logger.exception("position adapter failed for %s: %s", broker, e)
                return error("broker_error", f"position adapter failed: {e}"), 502
            return ok({
                "positions": [
                    {
                        "instrument_id": str(p.instrument_id),
                        "venue_code": p.venue_code,
                        "canonical_symbol": p.canonical_symbol,
                        "quantity": str(p.quantity),
                        "average_price": str(p.average_price) if p.average_price is not None else None,
                        "market_value": str(p.market_value) if p.market_value is not None else None,
                        "realized_pnl": str(p.realized_pnl) if p.realized_pnl is not None else None,
                        "unrealized_pnl": str(p.unrealized_pnl) if p.unrealized_pnl is not None else None,
                        "currency": p.currency,
                    }
                    for p in positions
                ]
            }), 200

        # Non-India broker without an adapter: fail-closed.
        if not _broker_is_india(broker):
            try:
                from utils.metrics import counter

                counter(
                    "broker_adapter_missing_total",
                    {"broker": broker or "unknown", "feature": "positions"},
                )
            except Exception:  # pragma: no cover
                pass
            return error(
                ErrorCode.PROMOTED_CAPABILITY_UNAVAILABLE,
                f"positions are not available for broker {broker!r} — no "
                "BrokerPositionAdapter registered.",
                details={
                    "broker_code": broker,
                    "sub_code": ErrorCode.POSITION_ADAPTER_NOT_REGISTERED,
                },
            ), 503

        # India broker — legacy fallback path. Uses
        # ``services.positionbook_service`` which is the actual v1
        # India service for positions; the v3-era v2 skeleton named
        # the wrong module (``services.positions_service``) which
        # returned 501 for India brokers. v4 Phase 5 wires the
        # correct module so India v2 positions actually work.
        try:
            from services.positionbook_service import get_positionbook_with_auth
        except Exception as e:
            return error("unimplemented",
                         f"positions service not available: {e}"), 501

        ok_flag, resp, status = get_positionbook_with_auth(
            auth_token=auth_token, broker=broker
        )
        if not ok_flag:
            return error("broker_error",
                         resp.get("message", "positions fetch failed")), status

        rows = resp.get("data", [])
        return ok({"positions": rows}), 200


@balances_api.route("")
@balances_api.route("/")
class Balances(Resource):
    def get(self):
        auth_token, broker, auth_err = resolve_auth()
        if auth_err is not None:
            return error("unauthorized", auth_err), 401

        from services.broker_market_data_registry import (
            get_broker_balance_adapter,
        )

        adapter = get_broker_balance_adapter(broker or "")
        if adapter is not None:
            try:
                balance = adapter.get_balance(_account_ctx(broker, auth_token))
            except Exception as e:
                logger.exception("balance adapter failed for %s: %s", broker, e)
                return error("broker_error", f"balance adapter failed: {e}"), 502
            return ok({
                "balance": {
                    "cash": str(balance.cash),
                    "equity": str(balance.equity) if balance.equity is not None else None,
                    "buying_power": str(balance.buying_power) if balance.buying_power is not None else None,
                    "margin_used": str(balance.margin_used) if balance.margin_used is not None else None,
                    "currency": balance.currency,
                }
            }), 200

        if not _broker_is_india(broker):
            try:
                from utils.metrics import counter

                counter(
                    "broker_adapter_missing_total",
                    {"broker": broker or "unknown", "feature": "balances"},
                )
            except Exception:  # pragma: no cover
                pass
            return error(
                ErrorCode.PROMOTED_CAPABILITY_UNAVAILABLE,
                f"balances are not available for broker {broker!r} — no "
                "BrokerBalanceAdapter registered.",
                details={
                    "broker_code": broker,
                    "sub_code": ErrorCode.BALANCE_ADAPTER_NOT_REGISTERED,
                },
            ), 503

        try:
            from services.funds_service import get_funds_with_auth
        except Exception as e:
            return error("unimplemented",
                         f"funds service not available: {e}"), 501

        ok_flag, resp, status = get_funds_with_auth(
            auth_token=auth_token, broker=broker
        )
        if not ok_flag:
            return error("broker_error", resp.get("message", "funds fetch failed")), status

        return ok({"balances": resp.get("data", {})}), 200
