"""v6 Phase 7 — RMoney v2 broker translator (XTS-family)."""

from __future__ import annotations

from broker._xts_family import XTSFamilyOrderTranslator

BROKER_CODE = "rmoney"


class RMoneyOrderTranslator(XTSFamilyOrderTranslator):
    broker_code = BROKER_CODE


def install_rmoney_translator() -> RMoneyOrderTranslator:
    from services.broker_translator_registry import register_broker_translator

    t = RMoneyOrderTranslator()
    register_broker_translator(t)
    return t


__all__ = ["BROKER_CODE", "RMoneyOrderTranslator", "install_rmoney_translator"]
