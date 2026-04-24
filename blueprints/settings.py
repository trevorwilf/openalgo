# blueprints/settings.py

from flask import Blueprint, jsonify, request, session

from database.settings_db import get_analyze_mode, get_default_market_region, set_analyze_mode
from sandbox.execution_thread import start_execution_engine, stop_execution_engine
from services.market_region_service import (
    get_market_region_catalog,
    update_default_market_region,
)
from utils.logging import get_logger
from utils.session import check_session_validity

logger = get_logger(__name__)

settings_bp = Blueprint("settings_bp", __name__, url_prefix="/settings")


@settings_bp.route("/analyze-mode")
@check_session_validity
def get_mode():
    """Get current analyze mode setting"""
    try:
        return jsonify({"analyze_mode": get_analyze_mode()})
    except Exception as e:
        logger.exception(f"Error getting analyze mode: {str(e)}")
        return jsonify({"error": "Failed to get analyze mode"}), 500


@settings_bp.route("/analyze-mode/<int:mode>", methods=["POST"])
@check_session_validity
def set_mode(mode):
    """Set analyze mode setting and manage execution engine thread"""
    try:
        set_analyze_mode(bool(mode))
        mode_name = "Analyze" if mode else "Live"

        # Start or stop execution engine based on mode
        if mode:
            # Starting Analyze mode - start execution engine
            success, message = start_execution_engine()
            if success:
                logger.info("Execution engine started for Analyze mode")
            else:
                logger.warning(f"Failed to start execution engine: {message}")
        else:
            # Switching to Live mode - stop execution engine
            success, message = stop_execution_engine()
            if success:
                logger.info("Execution engine stopped for Live mode")
            else:
                logger.warning(f"Failed to stop execution engine: {message}")

        return jsonify(
            {
                "success": True,
                "analyze_mode": bool(mode),
                "message": f"Switched to {mode_name} Mode",
            }
        )
    except Exception as e:
        logger.exception(f"Error setting analyze mode: {str(e)}")
        return jsonify({"error": "Failed to set analyze mode"}), 500


@settings_bp.route("/market-regions", methods=["GET"])
@check_session_validity
def list_market_regions():
    """Return the installed market-region plugins and current default."""
    try:
        broker = session.get("broker")
        payload = get_market_region_catalog(active_broker=broker)
        return jsonify({"success": True, **payload})
    except Exception as e:
        logger.exception(f"Error listing market regions: {str(e)}")
        return jsonify({"error": "Failed to load market regions"}), 500


@settings_bp.route("/default-region", methods=["GET"])
@check_session_validity
def get_default_region():
    """Return only the persisted default market-region code."""
    try:
        return jsonify(
            {
                "success": True,
                "default_region": get_default_market_region(),
            }
        )
    except Exception as e:
        logger.exception(f"Error getting default market region: {str(e)}")
        return jsonify({"error": "Failed to get default market region"}), 500


@settings_bp.route("/default-region", methods=["POST"])
@check_session_validity
def set_default_region():
    """Set the persistent default market-region code."""
    try:
        payload = request.get_json(silent=True) or request.form or {}
        region_code = payload.get("region_code") or payload.get("default_region")
        if region_code is None:
            return jsonify({"error": "region_code is required"}), 400

        broker = session.get("broker")
        result = update_default_market_region(region_code, active_broker=broker)
        return jsonify({"success": True, **result})
    except ValueError as e:
        return jsonify({"error": str(e)}), 400
    except Exception as e:
        logger.exception(f"Error setting default market region: {str(e)}")
        return jsonify({"error": "Failed to set default market region"}), 500
