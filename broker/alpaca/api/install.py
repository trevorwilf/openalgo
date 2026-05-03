"""Alpaca promoted-lane adapter registration.

Single entry point — :func:`install_alpaca_adapters` — that wires
every Alpaca-side promoted-lane contract into its registry:

  * :class:`AlpacaQuoteAdapter`     → quotes registry
  * :class:`AlpacaBarAdapter`       → bars registry
  * :class:`AlpacaPositionAdapter`  → positions registry
  * :class:`AlpacaBalanceAdapter`   → balances registry

Called from ``app.setup_environment`` so the adapters are live as
soon as the Flask app is built. Registration is idempotent — re-
running the installer (e.g., in tests) replaces existing entries
in the broker-keyed registry dict.
"""

from __future__ import annotations

from utils.logging import get_logger


logger = get_logger(__name__)


def install_alpaca_adapters() -> None:
    """Register every Alpaca promoted-lane adapter."""
    try:
        from broker.alpaca.api.bar_api import AlpacaBarAdapter
        from broker.alpaca.api.position_balance_adapters import (
            AlpacaBalanceAdapter,
            AlpacaPositionAdapter,
        )
        from broker.alpaca.api.quote_api import AlpacaQuoteAdapter
        from services.broker_market_data_registry import (
            register_broker_balance_adapter,
            register_broker_bar_adapter,
            register_broker_position_adapter,
            register_broker_quote_adapter,
        )
    except Exception as e:
        logger.exception("Alpaca adapter import failed: %s", e)
        return

    register_broker_quote_adapter(AlpacaQuoteAdapter())
    register_broker_bar_adapter(AlpacaBarAdapter())
    register_broker_position_adapter(AlpacaPositionAdapter())
    register_broker_balance_adapter(AlpacaBalanceAdapter())
    logger.info(
        "Alpaca promoted-lane adapters registered: quote/bar/position/balance"
    )


__all__ = ["install_alpaca_adapters"]
