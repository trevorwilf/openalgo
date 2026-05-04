from typing import Any, Dict, Optional, Tuple

from sqlalchemy.orm.exc import NoResultFound

from database.auth_db import get_auth_token_broker
from database.symbol import SymToken, SymTokenV1Read, db_session
from utils.logging import get_logger

# Initialize logger
logger = get_logger(__name__)

# v8-C — query the symtoken_v1 view first when the operator has run
# the broker-provenance migration. The view hides T-06 columns
# (broker_code / instrument_id) so v1 callers can't accidentally
# leak them. Set OPENALGO_SYMTOKEN_V1_VIEW=0 to disable view-first
# behavior (rollback escape hatch). When the view doesn't exist
# (operator hasn't migrated), the helper falls back to SymToken.
import os as _os
_USE_V1_VIEW = _os.environ.get("OPENALGO_SYMTOKEN_V1_VIEW", "1") != "0"
_V1_VIEW_AVAILABLE: bool | None = None  # tri-state probe cache


def _v1_view_is_available() -> bool:
    """Cached probe — does the symtoken_v1 view exist?

    Probes once per process. The migration that creates the view is
    run by the operator out-of-band; until then, the v1-lane lookup
    falls back to the SymToken table (same v1-shaped result).
    """
    global _V1_VIEW_AVAILABLE
    if _V1_VIEW_AVAILABLE is not None:
        return _V1_VIEW_AVAILABLE
    if not _USE_V1_VIEW:
        _V1_VIEW_AVAILABLE = False
        return False
    try:
        db_session.query(SymTokenV1Read).limit(1).all()
        _V1_VIEW_AVAILABLE = True
    except Exception:
        # OperationalError "no such table: symtoken_v1" is the
        # expected pre-migration outcome — fall back silently.
        _V1_VIEW_AVAILABLE = False
    return _V1_VIEW_AVAILABLE


def get_symbol_info_for_broker(
    symbol: str, exchange: str, broker_code: str,
) -> Optional["SymToken"]:
    """v7 Phase 4-bis-5 — broker-aware symbol lookup.

    Filters by ``broker_code`` so two brokers that both register
    the same canonical ``(symbol, exchange)`` pair (post-T-06
    cross-broker scenario) return their respective rows. Returns
    ``None`` when no row matches.

    Backward-compatible behavior: if ``broker_code`` is empty the
    function falls back to ``(symbol, exchange)`` matching only —
    matches the legacy ``get_symbol_info_with_auth`` lookup.
    """
    query = db_session.query(SymToken).filter(
        SymToken.symbol == symbol, SymToken.exchange == exchange
    )
    if broker_code:
        # Match the operator's broker explicitly. Pre-backfill
        # rows have broker_code=NULL so they're filtered out —
        # once the operator runs migrate_symtoken_broker_provenance.py
        # the rows pick up broker_code and become matchable.
        query = query.filter(SymToken.broker_code == broker_code)
    return query.first()


def get_symbol_info_with_auth(
    symbol: str, exchange: str, auth_token: str, broker: str
) -> tuple[bool, dict[str, Any], int]:
    """
    Get symbol information using provided auth token.

    Args:
        symbol: Symbol to look up
        exchange: Exchange to look up the symbol in
        auth_token: Authentication token for the broker API
        broker: Name of the broker

    Returns:
        Tuple containing:
        - Success status (bool)
        - Response data (dict)
        - HTTP status code (int)
    """
    try:
        # v8-C — v1 lookup goes through symtoken_v1 view when
        # available (hides T-06 broker_code / instrument_id from
        # v1 responses). Falls back to SymToken when the view
        # doesn't exist (pre-migration operator).
        if _v1_view_is_available():
            result = (
                db_session.query(SymTokenV1Read)
                .filter(
                    SymTokenV1Read.symbol == symbol,
                    SymTokenV1Read.exchange == exchange,
                )
                .first()
            )
        else:
            result = (
                db_session.query(SymToken)
                .filter(SymToken.symbol == symbol, SymToken.exchange == exchange)
                .first()
            )

        if result is None:
            error_response = {
                "status": "error",
                "message": f"Symbol {symbol} not found in exchange {exchange}",
            }
            return False, error_response, 404

        # Get freeze quantity
        from database.qty_freeze_db import get_freeze_qty_for_option

        freeze_qty = get_freeze_qty_for_option(result.symbol, result.exchange)

        # Transform the SymToken object to a dictionary
        symbol_info = {
            "id": result.id,
            "symbol": result.symbol,
            "brsymbol": result.brsymbol,
            "name": result.name,
            "exchange": result.exchange,
            "brexchange": result.brexchange,
            "token": result.token,
            "expiry": result.expiry,
            "strike": result.strike,
            "lotsize": result.lotsize,
            "instrumenttype": result.instrumenttype,
            "tick_size": result.tick_size,
            "freeze_qty": freeze_qty,
        }

        response_data = {"data": symbol_info, "status": "success"}

        return True, response_data, 200

    except NoResultFound:
        error_response = {
            "status": "error",
            "message": f"Symbol {symbol} not found in exchange {exchange}",
        }
        return False, error_response, 404

    except Exception as e:
        logger.exception(f"Error retrieving symbol information: {e}")
        error_response = {"status": "error", "message": str(e)}
        return False, error_response, 500


def get_symbol_info(
    symbol: str,
    exchange: str,
    api_key: str | None = None,
    auth_token: str | None = None,
    broker: str | None = None,
) -> tuple[bool, dict[str, Any], int]:
    """
    Get symbol information for a given symbol and exchange.
    Supports both API-based authentication and direct internal calls.

    Args:
        symbol: Symbol to look up
        exchange: Exchange to look up the symbol in
        api_key: OpenAlgo API key (for API-based calls)
        auth_token: Direct broker authentication token (for internal calls)
        broker: Direct broker name (for internal calls)

    Returns:
        Tuple containing:
        - Success status (bool)
        - Response data (dict)
        - HTTP status code (int)
    """
    # Case 1: API-based authentication
    if api_key and not (auth_token and broker):
        AUTH_TOKEN, broker_name = get_auth_token_broker(api_key)
        if AUTH_TOKEN is None:
            error_response = {"status": "error", "message": "Invalid openalgo apikey"}
            return False, error_response, 403

        return get_symbol_info_with_auth(symbol, exchange, AUTH_TOKEN, broker_name)

    # Case 2: Direct internal call with auth_token and broker
    elif auth_token and broker:
        return get_symbol_info_with_auth(symbol, exchange, auth_token, broker)

    # Case 3: No authentication required for this endpoint
    # Symbol information can be accessed without authentication
    elif not api_key and not auth_token and not broker:
        # Use a dummy auth token and broker since they're not used in the actual implementation
        return get_symbol_info_with_auth(symbol, exchange, "", "")

    # Case 4: Invalid parameters
    else:
        error_response = {
            "status": "error",
            "message": "Either api_key or both auth_token and broker must be provided",
        }
        return False, error_response, 400
