"""v6 Phase 7 — JainamXTS v2 broker translator (XTS-family)."""

from __future__ import annotations

from broker._xts_family import XTSFamilyOrderTranslator

BROKER_CODE = "jainamxts"


class JainamXTSOrderTranslator(XTSFamilyOrderTranslator):
    broker_code = BROKER_CODE


def install_jainamxts_translator() -> JainamXTSOrderTranslator:
    from services.broker_translator_registry import register_broker_translator

    t = JainamXTSOrderTranslator()
    register_broker_translator(t)
    return t


__all__ = ["BROKER_CODE", "JainamXTSOrderTranslator", "install_jainamxts_translator"]
