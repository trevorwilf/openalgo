"""v6 Phase 7 — Wisdom Capital v2 broker translator (XTS-family)."""

from __future__ import annotations

from broker._xts_family import XTSFamilyOrderTranslator

BROKER_CODE = "wisdom"


class WisdomOrderTranslator(XTSFamilyOrderTranslator):
    broker_code = BROKER_CODE


def install_wisdom_translator() -> WisdomOrderTranslator:
    from services.broker_translator_registry import register_broker_translator

    t = WisdomOrderTranslator()
    register_broker_translator(t)
    return t


__all__ = ["BROKER_CODE", "WisdomOrderTranslator", "install_wisdom_translator"]
