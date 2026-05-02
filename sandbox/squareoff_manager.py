# sandbox/squareoff_manager.py
"""
Square-Off Manager - Handles automatic position closure at exchange-specific times

Features:
- Auto square-off for MIS positions at configured times
- Exchange-specific timings (NSE/BSE: 3:15 PM, CDS/BCD: 4:45 PM, MCX: 11:30 PM, NCDEX: 5:00 PM)
- Market order creation for position closure
- Background scheduler for automatic execution
- Configurable square-off times
"""

import os
import sys
from datetime import datetime, time
from decimal import Decimal

import pytz

# Add parent directory to path
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from database.sandbox_db import SandboxPositions, db_session, get_config
from sandbox.position_manager import PositionManager
from utils.logging import get_logger

logger = get_logger(__name__)


class SquareOffManager:
    """Manages automatic square-off of MIS positions"""

    def __init__(self):
        # Phase 2 T-10 — IST timezone re-exported from market_regions.
        from market_regions.india.sessions import IST
        self.ist = IST

        # Phase 2-bis-1 (T-11 wiring) — defaults sourced from
        # ``market_regions.india.squareoff.MANDATORY_CLOSE_RULES``.
        # Operator overrides via ``get_config(...)`` continue to take
        # precedence; the region plugin only supplies the defaults.
        # Pre-Phase-2-bis the defaults were hardcoded at the
        # call-site; this change makes the region the single source
        # of truth for the default HH:MM values.
        from market_regions.india.squareoff import MANDATORY_CLOSE_RULES

        venue_defaults: dict[str, str] = {
            rule["venue"]: rule["local_close"]
            for rule in MANDATORY_CLOSE_RULES
        }

        # Map config-key → default lookup. The legacy keys group
        # NSE/BSE/NFO/BFO under one knob and CDS/BCD under another;
        # we preserve that grouping by reading the first venue's
        # default in each group.
        nse_bse_default = venue_defaults.get("NSE", "15:15")
        cds_bcd_default = venue_defaults.get("CDS", "16:45")
        mcx_default = venue_defaults.get("MCX", "23:30")
        ncdex_default = venue_defaults.get("NCDEX", "17:00")

        self.square_off_times = {
            "NSE": self._parse_time(get_config("nse_bse_square_off_time", nse_bse_default)),
            "BSE": self._parse_time(get_config("nse_bse_square_off_time", nse_bse_default)),
            "NFO": self._parse_time(get_config("nse_bse_square_off_time", nse_bse_default)),
            "BFO": self._parse_time(get_config("nse_bse_square_off_time", nse_bse_default)),
            "CDS": self._parse_time(get_config("cds_bcd_square_off_time", cds_bcd_default)),
            "BCD": self._parse_time(get_config("cds_bcd_square_off_time", cds_bcd_default)),
            "MCX": self._parse_time(get_config("mcx_square_off_time", mcx_default)),
            "NCDEX": self._parse_time(get_config("ncdex_square_off_time", ncdex_default)),
        }

    def _parse_time(self, time_str):
        """Parse time string (HH:MM) to time object"""
        try:
            hour, minute = map(int, time_str.split(":"))
            return time(hour=hour, minute=minute)
        except Exception as e:
            logger.exception(f"Error parsing time '{time_str}': {e}")
            return time(15, 15)  # Default to 3:15 PM

    def check_and_square_off(self):
        """
        Check if it's time to square-off positions and execute
        Should be called frequently (e.g., every minute)
        """
        try:
            now = datetime.now(self.ist)
            current_time = now.time()

            # Step 1: Cancel all open MIS orders past square-off time
            self._cancel_open_mis_orders(current_time)

            # Step 2: Get all open MIS positions (quantity != 0)
            mis_positions = (
                SandboxPositions.query.filter_by(product="MIS")
                .filter(SandboxPositions.quantity != 0)
                .all()
            )

            if not mis_positions:
                logger.debug("No MIS positions to square-off")
                return

            positions_to_close = []

            # Check each position against its exchange's square-off time
            for position in mis_positions:
                exchange = position.exchange
                square_off_time = self.square_off_times.get(exchange)

                if not square_off_time:
                    logger.warning(f"No square-off time configured for exchange {exchange}")
                    continue

                # Check if current time has passed square-off time
                if current_time >= square_off_time:
                    positions_to_close.append(position)

            if positions_to_close:
                logger.info(f"Found {len(positions_to_close)} MIS positions to square-off")
                self._square_off_positions(positions_to_close)
            else:
                logger.debug(f"No positions due for square-off at {current_time.strftime('%H:%M')}")

        except Exception as e:
            logger.exception(f"Error checking square-off conditions: {e}")

    def _cancel_open_mis_orders(self, current_time):
        """Cancel all open MIS orders past their exchange's square-off time"""
        try:
            from database.sandbox_db import SandboxOrders
            from sandbox.order_manager import OrderManager

            # Get all open MIS orders
            open_orders = SandboxOrders.query.filter_by(product="MIS", order_status="open").all()

            if not open_orders:
                return

            cancelled_count = 0

            for order in open_orders:
                exchange = order.exchange
                square_off_time = self.square_off_times.get(exchange)

                if not square_off_time:
                    continue

                # Check if current time has passed square-off time for this exchange
                if current_time >= square_off_time:
                    try:
                        order_manager = OrderManager(order.user_id)
                        success, response, status_code = order_manager.cancel_order(order.orderid)

                        if success:
                            logger.info(
                                f"Auto-cancelled MIS order {order.orderid} for {order.symbol} past square-off time"
                            )
                            cancelled_count += 1
                        else:
                            logger.error(
                                f"Failed to cancel MIS order {order.orderid}: {response.get('message', 'Unknown error')}"
                            )

                    except Exception as e:
                        logger.exception(f"Error cancelling MIS order {order.orderid}: {e}")

            if cancelled_count > 0:
                logger.info(
                    f"Auto-cancelled {cancelled_count} open MIS orders past square-off time"
                )

        except Exception as e:
            logger.exception(f"Error in _cancel_open_mis_orders: {e}")

    def _square_off_positions(self, positions):
        """Square-off a list of positions"""
        success_count = 0
        error_count = 0

        for position in positions:
            try:
                pm = PositionManager(position.user_id)
                success, response, status_code = pm.close_position(
                    position.symbol, position.exchange, position.product
                )

                if success:
                    logger.info(
                        f"Auto square-off: {position.symbol} for user {position.user_id} - "
                        f"OrderID: {response.get('orderid', 'N/A')}"
                    )
                    success_count += 1
                else:
                    logger.error(
                        f"Failed to square-off {position.symbol} for user {position.user_id}: "
                        f"{response.get('message', 'Unknown error')}"
                    )
                    error_count += 1

            except Exception as e:
                logger.exception(f"Error squaring-off position {position.symbol}: {e}")
                error_count += 1

        logger.info(f"Square-off completed: {success_count} successful, {error_count} failed")

    def force_square_off_all_mis(self):
        """Force square-off all MIS positions immediately"""
        try:
            mis_positions = (
                SandboxPositions.query.filter_by(product="MIS")
                .filter(SandboxPositions.quantity != 0)
                .all()
            )

            if not mis_positions:
                logger.info("No MIS positions to force square-off")
                return True, "No positions to square-off"

            logger.warning(f"Force squaring-off {len(mis_positions)} MIS positions")
            self._square_off_positions(mis_positions)

            return True, f"Force square-off initiated for {len(mis_positions)} positions"

        except Exception as e:
            logger.exception(f"Error force squaring-off positions: {e}")
            return False, f"Error: {str(e)}"

    def get_time_to_square_off(self, exchange):
        """Get time remaining until square-off for an exchange"""
        try:
            square_off_time = self.square_off_times.get(exchange)

            if not square_off_time:
                return None

            now = datetime.now(self.ist)
            current_time = now.time()

            # Create datetime objects for comparison
            square_off_dt = datetime.combine(now.date(), square_off_time)
            current_dt = datetime.combine(now.date(), current_time)

            # Calculate time difference
            time_diff = square_off_dt - current_dt

            # If time has passed, return 0 or negative
            return time_diff.total_seconds()

        except Exception as e:
            logger.exception(f"Error calculating time to square-off: {e}")
            return None

    def get_square_off_status(self):
        """Get status of square-off times for all exchanges"""
        try:
            now = datetime.now(self.ist)
            current_time = now.time()

            status = {}

            for exchange, square_off_time in self.square_off_times.items():
                time_to_square_off = self.get_time_to_square_off(exchange)

                status[exchange] = {
                    "square_off_time": square_off_time.strftime("%H:%M"),
                    "current_time": current_time.strftime("%H:%M"),
                    "time_remaining_seconds": int(time_to_square_off) if time_to_square_off else 0,
                    "is_past_square_off": current_time >= square_off_time,
                }

            return status

        except Exception as e:
            logger.exception(f"Error getting square-off status: {e}")
            return {}


def run_square_off_check():
    """Run one cycle of square-off check"""
    som = SquareOffManager()
    som.check_and_square_off()


if __name__ == "__main__":
    """Run square-off manager in standalone mode"""
    import time as time_module

    logger.info("Starting Sandbox Square-Off Manager")

    from database.sandbox_db import init_db

    init_db()

    som = SquareOffManager()

    # Display square-off times
    status = som.get_square_off_status()
    logger.info("Configured square-off times:")
    for exchange, info in status.items():
        logger.info(f"  {exchange}: {info['square_off_time']} IST")

    # Run check every minute
    check_interval = 60  # 1 minute

    try:
        while True:
            run_square_off_check()
            time_module.sleep(check_interval)
    except KeyboardInterrupt:
        logger.info("Square-off manager stopped by user")
    except Exception as e:
        logger.exception(f"Square-off manager error: {e}")
