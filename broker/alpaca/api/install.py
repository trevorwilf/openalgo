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
        from broker.alpaca.api.order_api import AlpacaOrderTranslator
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
        from services.broker_translator_registry import (
            register_broker_translator,
        )
    except Exception as e:
        logger.exception("Alpaca adapter import failed: %s", e)
        return

    register_broker_quote_adapter(AlpacaQuoteAdapter())
    register_broker_bar_adapter(AlpacaBarAdapter())
    register_broker_position_adapter(AlpacaPositionAdapter())
    register_broker_balance_adapter(AlpacaBalanceAdapter())
    register_broker_translator(AlpacaOrderTranslator())
    _seed_alpaca_order_rules()
    logger.info(
        "Alpaca promoted-lane adapters registered: "
        "quote/bar/position/balance/translator/rules"
    )


def _seed_alpaca_order_rules() -> None:
    """Seed `broker_order_rules` with Alpaca's allowed shapes.

    Two rule rows: one for US equity (XNAS/XNYS/ARCX/BATS), one for
    crypto (ALPACA_CRYPTO). Idempotent — `rules_upsert` keys on the
    qualifier columns and overwrites the allowlists on each call.
    """
    try:
        from database.broker_rules_repo import (
            init_broker_rules_tables,
            rules_upsert,
        )
    except Exception:  # pragma: no cover
        logger.exception("broker_rules_repo unavailable; skipping Alpaca rules seed")
        return

    try:
        init_broker_rules_tables()
    except Exception:  # pragma: no cover - additive migration helper
        logger.exception("init_broker_rules_tables failed; continuing")

    EQUITY_ORDER_TYPES = [
        "MARKET",
        "LIMIT",
        "STOP",
        "STOP_LIMIT",
        "TRAILING_STOP",
    ]
    EQUITY_TIF = ["DAY", "GTC", "OPG", "ATC", "IOC", "FOK"]
    CRYPTO_ORDER_TYPES = ["MARKET", "LIMIT", "STOP_LIMIT"]
    CRYPTO_TIF = ["GTC", "IOC", "FOK"]

    EQUITY_VENUES = ["XNAS", "XNYS", "ARCX", "BATS"]

    try:
        for venue in EQUITY_VENUES:
            rules_upsert(
                broker_code="alpaca",
                venue_code=venue,
                asset_class="EQUITY",
                allowed_order_types=EQUITY_ORDER_TYPES,
                allowed_time_in_force=EQUITY_TIF,
                allows_fractional=True,
                allows_notional=True,
                allows_short=True,
            )
        rules_upsert(
            broker_code="alpaca",
            venue_code="ALPACA_CRYPTO",
            asset_class="SPOT",
            allowed_order_types=CRYPTO_ORDER_TYPES,
            allowed_time_in_force=CRYPTO_TIF,
            allows_fractional=True,
            allows_short=False,
        )
        logger.info(
            "Alpaca broker rules seeded: %d equity venues + crypto",
            len(EQUITY_VENUES),
        )
    except Exception:
        logger.exception("Alpaca broker rules seed failed; promoted orders may 422")


__all__ = ["install_alpaca_adapters"]
