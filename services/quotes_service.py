import importlib
from typing import Any, Dict, List, Optional, Tuple, Union

from database.auth_db import get_auth_token_broker
from domain.errors import MissingRegionContext
from services.market_region_service import get_allowed_venue_codes_for_active_region
from utils.feature_flags import is_enabled
from utils.logging import get_logger

# Phase 3 (T-20) — ``database.token_db.get_token`` is a LEGACY_INDIA
# primitive forbidden in PROMOTED_CORE. Imported lazily inside
# :func:`validate_symbol_exchange` so the module-level import surface
# stays clean while the legacy v1-lane fallback continues to work
# bit-identically. ADR 0016 / ADR 0019 — the canonical resolver lives
# at ``services.instrument_resolution.resolve_instrument``; promoted
# (v2) routes already use it. The v1 services keep ``get_token`` for
# parity until Phase 9 physically relocates the v1 lane.

# Initialize logger
logger = get_logger(__name__)


def _run_resolver_for_observability(symbol: str, exchange: str, broker: str) -> None:
    """Phase 3a: query the new instrument resolver alongside the legacy
    path for observability. Does NOT change the broker API call — that
    remains the legacy `get_token`-driven flow. Gated by ``RESOLVER_V2``.

    Any exception is caught and logged. This function never changes
    control flow for the caller, so the `/api/v1` response stays
    byte-identical whether the flag is on or off.
    """
    if not is_enabled("RESOLVER_V2"):
        return
    try:
        from services.instrument_resolver import (
            ResolverAmbiguous,
            ResolverMiss,
            get_resolver,
        )
    except Exception as e:  # import error — defensive; never fail the quote
        logger.debug("resolver unavailable (import failed): %s", e)
        return

    try:
        resolved = get_resolver().resolve_for_quote(
            symbol=symbol, exchange=exchange, broker_code=broker
        )
        logger.debug(
            "resolver_hit symbol=%s exchange=%s broker=%s legacy_fallback=%s "
            "instrument_id=%s",
            symbol, exchange, broker,
            resolved.legacy_fallback, resolved.instrument_id,
        )
    except ResolverMiss as e:
        logger.warning(
            "resolver_miss_falling_back symbol=%s exchange=%s broker=%s: %s",
            symbol, exchange, broker, e,
        )
    except ResolverAmbiguous as e:
        logger.warning(
            "resolver_ambiguous_falling_back symbol=%s exchange=%s broker=%s: %s",
            symbol, exchange, broker, e,
        )
    except Exception as e:
        # Never 500 on a resolver bug — the legacy path is authoritative.
        logger.exception(
            "resolver_exception symbol=%s exchange=%s broker=%s: %s",
            symbol, exchange, broker, e,
        )


def validate_symbol_exchange(symbol: str, exchange: str) -> tuple[bool, str | None]:
    """
    Validate that a symbol exists for the given exchange.

    Args:
        symbol: Trading symbol
        exchange: Exchange (e.g., NSE, NFO)

    Returns:
        Tuple of (is_valid, error_message)
    """
    # Validate exchange — Phase 3 (T-20) region-aware vocabulary lookup.
    exchange_upper = exchange.upper()
    try:
        valid_exchanges = get_allowed_venue_codes_for_active_region()
    except MissingRegionContext as exc:
        return False, f"Cannot validate quote: {exc}"
    if exchange_upper not in valid_exchanges:
        return False, f"Invalid exchange '{exchange}'. Must be one of: {', '.join(valid_exchanges)}"

    # Validate symbol exists in master contract — Phase 3 keeps the
    # legacy ``get_token`` lookup function-local so PROMOTED_CORE
    # module-level import lock stays clean.
    from database.token_db import get_token

    token = get_token(symbol, exchange_upper)
    if token is None:
        return (
            False,
            f"Symbol '{symbol}' not found for exchange '{exchange}'. Please verify the symbol name and ensure master contracts are downloaded.",
        )

    return True, None


def validate_symbols_bulk(
    symbols: list[dict[str, str]],
) -> tuple[bool, list[dict[str, Any]], str | None]:
    """
    Validate multiple symbols and their exchanges.

    Args:
        symbols: List of dicts with 'symbol' and 'exchange' keys

    Returns:
        Tuple of (all_valid, validated_symbols_with_errors, first_error_message)
    """
    all_valid = True
    validated = []
    first_error = None

    for item in symbols:
        symbol = item.get("symbol", "")
        exchange = item.get("exchange", "")

        if not symbol or not exchange:
            error = "Missing symbol or exchange in request"
            validated.append({**item, "valid": False, "error": error})
            if all_valid:
                first_error = error
                all_valid = False
            continue

        is_valid, error = validate_symbol_exchange(symbol, exchange)
        validated.append({**item, "valid": is_valid, "error": error})

        if not is_valid and all_valid:
            first_error = error
            all_valid = False

    return all_valid, validated, first_error


def import_broker_module(broker_name: str) -> Any | None:
    """
    Dynamically import the broker-specific data module.

    Args:
        broker_name: Name of the broker

    Returns:
        The imported module or None if import fails
    """
    try:
        module_path = f"broker.{broker_name}.api.data"
        broker_module = importlib.import_module(module_path)
        return broker_module
    except ImportError as error:
        logger.error(f"Error importing broker module '{module_path}': {error}")
        return None


def get_quotes_with_auth(
    auth_token: str, feed_token: str | None, broker: str, symbol: str, exchange: str
) -> tuple[bool, dict[str, Any], int]:
    """
    Get real-time quotes for a symbol using provided auth tokens.

    Args:
        auth_token: Authentication token for the broker API
        feed_token: Feed token for market data (if required by broker)
        broker: Name of the broker
        symbol: Trading symbol
        exchange: Exchange (e.g., NSE, BSE)

    Returns:
        Tuple containing:
        - Success status (bool)
        - Response data (dict)
        - HTTP status code (int)
    """
    # Validate symbol and exchange before making broker API call
    is_valid, error_msg = validate_symbol_exchange(symbol, exchange)
    if not is_valid:
        return False, {"status": "error", "message": error_msg}, 400

    # Phase 3a: observability-only resolver probe. No control-flow effect.
    _run_resolver_for_observability(symbol, exchange, broker)

    broker_module = import_broker_module(broker)
    if broker_module is None:
        return False, {"status": "error", "message": "Broker-specific module not found"}, 404

    try:
        # Initialize broker's data handler based on broker's requirements
        if hasattr(broker_module.BrokerData.__init__, "__code__"):
            # Check number of parameters the broker's __init__ accepts
            param_count = broker_module.BrokerData.__init__.__code__.co_argcount
            if param_count > 2:  # More than self and auth_token
                data_handler = broker_module.BrokerData(auth_token, feed_token)
            else:
                data_handler = broker_module.BrokerData(auth_token)
        else:
            # Fallback to just auth token if we can't inspect
            data_handler = broker_module.BrokerData(auth_token)

        quotes = data_handler.get_quotes(symbol, exchange)

        if quotes is None:
            return False, {"status": "error", "message": "Failed to fetch quotes"}, 500

        return True, {"status": "success", "data": quotes}, 200
    except Exception as e:
        # Check if this is a permission error
        error_msg = str(e)
        if "permission" in error_msg.lower() or "insufficient" in error_msg.lower():
            # Log at debug level for permission errors (common with personal APIs)
            logger.debug(f"Quote fetch permission denied: {error_msg}")
        else:
            # Log other errors normally
            logger.exception(f"Error in broker_module.get_quotes: {e}")

        return False, {"status": "error", "message": str(e)}, 500


def get_quotes(
    symbol: str,
    exchange: str,
    api_key: str | None = None,
    auth_token: str | None = None,
    feed_token: str | None = None,
    broker: str | None = None,
) -> tuple[bool, dict[str, Any], int]:
    """
    Get real-time quotes for a symbol.
    Supports both API-based authentication and direct internal calls.

    Args:
        symbol: Trading symbol
        exchange: Exchange (e.g., NSE, BSE)
        api_key: OpenAlgo API key (for API-based calls)
        auth_token: Direct broker authentication token (for internal calls)
        feed_token: Direct broker feed token (for internal calls)
        broker: Direct broker name (for internal calls)

    Returns:
        Tuple containing:
        - Success status (bool)
        - Response data (dict)
        - HTTP status code (int)
    """
    # Case 1: API-based authentication
    if api_key and not (auth_token and broker):
        AUTH_TOKEN, FEED_TOKEN, broker_name = get_auth_token_broker(
            api_key, include_feed_token=True
        )
        if AUTH_TOKEN is None:
            return False, {"status": "error", "message": "Invalid openalgo apikey"}, 403
        return get_quotes_with_auth(AUTH_TOKEN, FEED_TOKEN, broker_name, symbol, exchange)

    # Case 2: Direct internal call with auth_token and broker
    elif auth_token and broker:
        return get_quotes_with_auth(auth_token, feed_token, broker, symbol, exchange)

    # Case 3: Invalid parameters
    else:
        return (
            False,
            {
                "status": "error",
                "message": "Either api_key or both auth_token and broker must be provided",
            },
            400,
        )


def get_multiquotes_with_auth(
    auth_token: str, feed_token: str | None, broker: str, symbols: list
) -> tuple[bool, dict[str, Any], int]:
    """
    Get real-time quotes for multiple symbols using provided auth tokens.

    Args:
        auth_token: Authentication token for the broker API
        feed_token: Feed token for market data (if required by broker)
        broker: Name of the broker
        symbols: List of dicts with 'symbol' and 'exchange' keys

    Returns:
        Tuple containing:
        - Success status (bool)
        - Response data (dict)
        - HTTP status code (int)
    """
    # Validate all symbols before making broker API calls
    all_valid, validated_symbols, first_error = validate_symbols_bulk(symbols)

    # Separate valid and invalid symbols
    valid_symbols = [item for item in validated_symbols if item.get("valid", False)]
    invalid_symbols = [item for item in validated_symbols if not item.get("valid", False)]

    # If no valid symbols, return error
    if not valid_symbols:
        return (
            False,
            {
                "status": "error",
                "message": first_error or "No valid symbols provided",
                "invalid_symbols": [
                    {
                        "symbol": s.get("symbol"),
                        "exchange": s.get("exchange"),
                        "error": s.get("error"),
                    }
                    for s in invalid_symbols
                ],
            },
            400,
        )

    broker_module = import_broker_module(broker)
    if broker_module is None:
        return False, {"status": "error", "message": "Broker-specific module not found"}, 404

    try:
        # Initialize broker's data handler based on broker's requirements
        if hasattr(broker_module.BrokerData.__init__, "__code__"):
            # Check number of parameters the broker's __init__ accepts
            param_count = broker_module.BrokerData.__init__.__code__.co_argcount
            if param_count > 2:  # More than self and auth_token
                data_handler = broker_module.BrokerData(auth_token, feed_token)
            else:
                data_handler = broker_module.BrokerData(auth_token)
        else:
            # Fallback to just auth token if we can't inspect
            data_handler = broker_module.BrokerData(auth_token)

        # Build results list starting with invalid symbols (marked as errors)
        results = []
        for item in invalid_symbols:
            results.append(
                {
                    "symbol": item.get("symbol"),
                    "exchange": item.get("exchange"),
                    "error": item.get("error"),
                }
            )

        # Check if broker supports multiquotes
        if not hasattr(data_handler, "get_multiquotes"):
            # Fallback: fetch quotes one by one for valid symbols only
            logger.debug(
                f"Broker {broker} doesn't support multiquotes, falling back to individual quotes"
            )
            for item in valid_symbols:
                try:
                    quote = data_handler.get_quotes(item["symbol"], item["exchange"])
                    results.append(
                        {"symbol": item["symbol"], "exchange": item["exchange"], "data": quote}
                    )
                except Exception as e:
                    logger.exception(
                        f"Error fetching quote for {item['exchange']}:{item['symbol']}: {e}"
                    )
                    results.append(
                        {"symbol": item["symbol"], "exchange": item["exchange"], "error": str(e)}
                    )

            return True, {"status": "success", "results": results}, 200

        # Use broker's native multiquotes method with only valid symbols
        # Strip validation metadata before passing to broker
        clean_symbols = [{"symbol": s["symbol"], "exchange": s["exchange"]} for s in valid_symbols]
        multiquotes = data_handler.get_multiquotes(clean_symbols)

        if multiquotes is None:
            return False, {"status": "error", "message": "Failed to fetch multiquotes"}, 500

        # Combine broker results with invalid symbol errors
        combined_results = results + (multiquotes if isinstance(multiquotes, list) else [])

        return True, {"status": "success", "results": combined_results}, 200
    except Exception as e:
        # Check if this is a permission error
        error_msg = str(e)
        if "permission" in error_msg.lower() or "insufficient" in error_msg.lower():
            # Log at debug level for permission errors (common with personal APIs)
            logger.debug(f"Multiquote fetch permission denied: {error_msg}")
        else:
            # Log other errors normally
            logger.exception(f"Error in broker_module.get_multiquotes: {e}")

        return False, {"status": "error", "message": str(e)}, 500


def get_multiquotes(
    symbols: list,
    api_key: str | None = None,
    auth_token: str | None = None,
    feed_token: str | None = None,
    broker: str | None = None,
) -> tuple[bool, dict[str, Any], int]:
    """
    Get real-time quotes for multiple symbols.
    Supports both API-based authentication and direct internal calls.

    Args:
        symbols: List of dicts with 'symbol' and 'exchange' keys
        api_key: OpenAlgo API key (for API-based calls)
        auth_token: Direct broker authentication token (for internal calls)
        feed_token: Direct broker feed token (for internal calls)
        broker: Direct broker name (for internal calls)

    Returns:
        Tuple containing:
        - Success status (bool)
        - Response data (dict)
        - HTTP status code (int)
    """
    # Case 1: API-based authentication
    if api_key and not (auth_token and broker):
        AUTH_TOKEN, FEED_TOKEN, broker_name = get_auth_token_broker(
            api_key, include_feed_token=True
        )
        if AUTH_TOKEN is None:
            return False, {"status": "error", "message": "Invalid openalgo apikey"}, 403
        return get_multiquotes_with_auth(AUTH_TOKEN, FEED_TOKEN, broker_name, symbols)

    # Case 2: Direct internal call with auth_token and broker
    elif auth_token and broker:
        return get_multiquotes_with_auth(auth_token, feed_token, broker, symbols)

    # Case 3: Invalid parameters
    else:
        return (
            False,
            {
                "status": "error",
                "message": "Either api_key or both auth_token and broker must be provided",
            },
            400,
        )
