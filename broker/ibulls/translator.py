"""v6 Phase 6 — IBulls Securities v2 broker translator (XTS-family)."""

from __future__ import annotations

from broker._xts_family import XTSFamilyOrderTranslator

BROKER_CODE = "ibulls"


class IBullsOrderTranslator(XTSFamilyOrderTranslator):
    broker_code = BROKER_CODE


def install_ibulls_translator() -> IBullsOrderTranslator:
    from services.broker_translator_registry import register_broker_translator

    t = IBullsOrderTranslator()
    register_broker_translator(t)
    return t


__all__ = ["BROKER_CODE", "IBullsOrderTranslator", "install_ibulls_translator"]
