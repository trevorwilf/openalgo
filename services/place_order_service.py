import copy
import importlib
from typing import Any, Dict, Optional, Tuple

from database.auth_db import get_auth_token_broker
from database.settings_db import get_analyze_mode
from domain.errors import MissingRegionContext
from events import AnalyzerErrorEvent, OrderFailedEvent, OrderPlacedEvent
from services.market_region_service import (
    get_allowed_action_codes_for_active_region,
    get_allowed_price_type_codes_for_active_region,
    get_allowed_product_codes_for_active_region,
    get_allowed_venue_codes_for_active_region,
)
from utils.event_bus import bus
from utils.logging import get_logger

# Phase 3 (T-20) — required-fields list is structural API contract, not
# a regional vocabulary. Inlined here so this module no longer imports
# from utils.constants and can move to PROMOTED_CORE.
_REQUIRED_ORDER_FIELDS: tuple[str, ...] = (
    "apikey", "strategy", "symbol", "exchange", "action", "quantity",
)

# Phase 3 (T-20) — ``restx_api.schemas`` is LEGACY_INDIA-classified;
# the OrderSchema instance is built lazily inside the validator so
# the module-level import surface stays clean. The OrderSchema is
# used only to coerce field types; its India-shaped venue / product
# enums are NOT relied on (Phase 3 added explicit region-aware
# validators above).
_order_schema_cached = None


def _get_order_schema():
    global _order_schema_cached
    if _order_schema_cached is None:
        from restx_api.schemas import OrderSchema as _OrderSchema
        _order_schema_cached = _OrderSchema()
    return _order_schema_cached

# Initialize logger
logger = get_logger(__name__)


def import_broker_module(broker_name: str) -> Any | None:
    """
    Dynamically import the broker-specific order API module.

    Args:
        broker_name: Name of the broker

    Returns:
        The imported module or None if import fails
    """
    try:
        module_path = f"broker.{broker_name}.api.order_api"
        broker_module = importlib.import_module(module_path)
        return broker_module
    except ImportError as error:
        logger.error(f"Error importing broker module '{module_path}': {error}")
        return None


def emit_analyzer_error(request_data: dict[str, Any], error_message: str) -> dict[str, Any]:
    """Publish an analyzer error event and return the error response dict."""
    error_response = {"mode": "analyze", "status": "error", "message": error_message}

    analyzer_request = request_data.copy()
    if "apikey" in analyzer_request:
        del analyzer_request["apikey"]
    analyzer_request["api_type"] = "placeorder"

    bus.publish(AnalyzerErrorEvent(
        mode="analyze",
        api_type="placeorder",
        request_data=analyzer_request,
        response_data=error_response,
        error_message=error_message,
    ))

    return error_response


def validate_order_data(data: dict[str, Any]) -> tuple[bool, dict[str, Any] | None, str | None]:
    """
    Validate order data against required fields and valid values

    Args:
        data: Order data to validate

    Returns:
        Tuple containing:
        - Success status (bool)
        - Validated order data (dict) or None if validation failed
        - Error message (str) or None if validation succeeded
    """
    # Check for missing mandatory fields
    missing_fields = [field for field in _REQUIRED_ORDER_FIELDS if field not in data]
    if missing_fields:
        return False, None, f"Missing mandatory field(s): {', '.join(missing_fields)}"

    # Phase 3 (T-20) — region-aware vocabulary lookup. Replaces the
    # legacy ``utils.constants.VALID_*`` imports; the active region's
    # manifest is the source of truth. India brokers continue to see
    # the same 11-venue / 3-product / 4-price-type set bit-identically;
    # non-India brokers (which never reach this v1 service per the
    # _v1_lane_guard) would see their own vocabulary.
    try:
        valid_exchanges = get_allowed_venue_codes_for_active_region()
        valid_actions = get_allowed_action_codes_for_active_region()
        valid_price_types = get_allowed_price_type_codes_for_active_region()
        valid_product_types = get_allowed_product_codes_for_active_region()
    except MissingRegionContext as exc:
        return False, None, f"Cannot validate order: {exc}"

    # Validate exchange
    if "exchange" in data and data["exchange"] not in valid_exchanges:
        return False, None, f"Invalid exchange. Must be one of: {', '.join(valid_exchanges)}"

    # Convert action to uppercase and validate
    if "action" in data:
        data["action"] = data["action"].upper()
        if data["action"] not in valid_actions:
            return (
                False,
                None,
                f"Invalid action. Must be one of: {', '.join(valid_actions)} (case insensitive)",
            )

    # Validate price type if provided
    if "price_type" in data and data["price_type"] not in valid_price_types:
        return False, None, f"Invalid price type. Must be one of: {', '.join(valid_price_types)}"

    # Validate product type if provided
    if "product_type" in data and data["product_type"] not in valid_product_types:
        return (
            False,
            None,
            f"Invalid product type. Must be one of: {', '.join(valid_product_types)}",
        )

    # Validate and deserialize input
    try:
        order_data = _get_order_schema().load(data)
        return True, order_data, None
    except Exception as err:
        return False, None, str(err)


def place_order_with_auth(
    order_data: dict[str, Any],
    auth_token: str,
    broker: str,
    original_data: dict[str, Any],
    emit_event: bool = True,
    prefetched_quote: dict[str, Any] | None = None,
) -> tuple[bool, dict[str, Any], int]:
    """
    Place an order using provided auth token.

    Args:
        order_data: Validated order data
        auth_token: Authentication token for the broker API
        broker: Name of the broker
        original_data: Original request data for logging
        emit_event: Whether to emit socket event (default True, set False for batch orders)
        prefetched_quote: Pre-fetched quote from batch call (optional, sandbox only)

    Returns:
        Tuple containing:
        - Success status (bool)
        - Response data (dict)
        - HTTP status code (int)
    """
    order_request_data = copy.deepcopy(original_data)
    if "apikey" in order_request_data:
        order_request_data.pop("apikey", None)

    api_key = original_data.get("apikey", "")

    # If in analyze mode, route to sandbox for virtual trading
    if get_analyze_mode():
        from services.sandbox_service import sandbox_place_order

        if not api_key:
            error_response = {
                "status": "error",
                "message": "API key required for sandbox mode",
                "mode": "analyze",
            }
            return False, error_response, 400

        success, response, status_code = sandbox_place_order(
            order_data, api_key, original_data, prefetched_quote=prefetched_quote
        )

        if emit_event:
            bus.publish(OrderPlacedEvent(
                mode="analyze",
                api_type="placeorder",
                strategy=order_data.get("strategy", ""),
                symbol=order_data.get("symbol", ""),
                exchange=order_data.get("exchange", ""),
                action=order_data.get("action", ""),
                quantity=int(order_data.get("quantity", 0)),
                pricetype=order_data.get("pricetype", ""),
                product=order_data.get("product", ""),
                orderid=response.get("orderid", ""),
                request_data=order_request_data,
                response_data=response,
                api_key=api_key,
            ))

        return success, response, status_code

    # If not in analyze mode, proceed with actual order placement
    broker_module = import_broker_module(broker)
    if broker_module is None:
        error_response = {"status": "error", "message": "Broker-specific module not found"}
        bus.publish(OrderFailedEvent(
            mode="live",
            api_type="placeorder",
            request_data=order_request_data,
            response_data=error_response,
            api_key=api_key,
            symbol=order_data.get("symbol", ""),
            exchange=order_data.get("exchange", ""),
            error_message="Broker-specific module not found",
        ))
        return False, error_response, 404

    try:
        res, response_data, order_id = broker_module.place_order_api(order_data, auth_token)
    except Exception as e:
        logger.exception(f"Error in broker_module.place_order_api: {e}")
        error_response = {
            "status": "error",
            "message": "Failed to place order due to internal error",
        }
        bus.publish(OrderFailedEvent(
            mode="live",
            api_type="placeorder",
            request_data=order_request_data,
            response_data=error_response,
            api_key=api_key,
            symbol=order_data.get("symbol", ""),
            exchange=order_data.get("exchange", ""),
            error_message=str(e),
        ))
        return False, error_response, 500

    if res.status == 200:
        order_response_data = {"status": "success", "orderid": order_id}

        if emit_event:
            bus.publish(OrderPlacedEvent(
                mode="live",
                api_type="placeorder",
                strategy=order_data.get("strategy", ""),
                symbol=order_data.get("symbol", ""),
                exchange=order_data.get("exchange", ""),
                action=order_data.get("action", ""),
                quantity=int(order_data.get("quantity", 0)),
                pricetype=order_data.get("pricetype", ""),
                product=order_data.get("product", ""),
                orderid=str(order_id),
                request_data=order_request_data,
                response_data=order_response_data,
                api_key=api_key,
            ))

        return True, order_response_data, 200
    else:
        message = (
            response_data.get("message", "Failed to place order")
            if isinstance(response_data, dict)
            else "Failed to place order"
        )
        error_response = {"status": "error", "message": message}
        bus.publish(OrderFailedEvent(
            mode="live",
            api_type="placeorder",
            request_data=order_request_data,
            response_data=error_response,
            api_key=api_key,
            symbol=order_data.get("symbol", ""),
            exchange=order_data.get("exchange", ""),
            error_message=message,
        ))
        return False, error_response, res.status if res.status != 200 else 500


def place_order(
    order_data: dict[str, Any],
    api_key: str | None = None,
    auth_token: str | None = None,
    broker: str | None = None,
    emit_event: bool = True,
    prefetched_quote: dict[str, Any] | None = None,
) -> tuple[bool, dict[str, Any], int]:
    """
    Place an order with the broker.
    Supports both API-based authentication and direct internal calls.

    Args:
        order_data: Order data containing all required fields
        api_key: OpenAlgo API key (for API-based calls)
        auth_token: Direct broker authentication token (for internal calls)
        broker: Direct broker name (for internal calls)
        emit_event: Whether to emit socket event (default True, set False for batch orders)
        prefetched_quote: Pre-fetched quote from batch call (optional, sandbox only).
            Skips per-order REST API quote fetch when provided.

    Returns:
        Tuple containing:
        - Success status (bool)
        - Response data (dict)
        - HTTP status code (int)
    """
    original_data = copy.deepcopy(order_data)
    if api_key:
        original_data["apikey"] = api_key
        # Also add apikey to order_data for validation
        order_data["apikey"] = api_key

    # Check if order should be routed to Action Center (semi-auto mode)
    # Only check for API-based calls, not internal calls
    if api_key and not (auth_token and broker):
        from services.order_router_service import queue_order, should_route_to_pending

        if should_route_to_pending(api_key, "placeorder"):
            return queue_order(api_key, original_data, "placeorder")

    # Validate the order data
    is_valid, _, error_message = validate_order_data(order_data)
    if not is_valid:
        if get_analyze_mode():
            return False, emit_analyzer_error(original_data, error_message), 400
        error_response = {"status": "error", "message": error_message}
        safe_request = {k: v for k, v in original_data.items() if k != "apikey"}
        bus.publish(OrderFailedEvent(
            mode="live",
            api_type="placeorder",
            request_data=safe_request,
            response_data=error_response,
            error_message=error_message,
            api_key=api_key or "",
        ))
        return False, error_response, 400

    # Case 1: API-based authentication
    if api_key and not (auth_token and broker):
        AUTH_TOKEN, broker_name = get_auth_token_broker(api_key)
        if AUTH_TOKEN is None:
            error_response = {"status": "error", "message": "Invalid openalgo apikey"}
            # Skip logging for invalid API keys to prevent database flooding
            return False, error_response, 403

        return place_order_with_auth(order_data, AUTH_TOKEN, broker_name, original_data, emit_event, prefetched_quote)

    # Case 2: Direct internal call with auth_token and broker
    elif auth_token and broker:
        return place_order_with_auth(order_data, auth_token, broker, original_data, emit_event, prefetched_quote)

    # Case 3: Invalid parameters
    else:
        error_response = {
            "status": "error",
            "message": "Either api_key or both auth_token and broker must be provided",
        }
        return False, error_response, 400
