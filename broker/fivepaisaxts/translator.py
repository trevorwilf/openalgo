"""v6 Phase 6 — 5paisa XTS v2 broker translator (XTS-family)."""

from __future__ import annotations

from broker._xts_family import XTSFamilyOrderTranslator

BROKER_CODE = "fivepaisaxts"


class FivePaisaXTSOrderTranslator(XTSFamilyOrderTranslator):
    broker_code = BROKER_CODE


def install_fivepaisaxts_translator() -> FivePaisaXTSOrderTranslator:
    from services.broker_translator_registry import register_broker_translator

    t = FivePaisaXTSOrderTranslator()
    register_broker_translator(t)
    return t


__all__ = ["BROKER_CODE", "FivePaisaXTSOrderTranslator", "install_fivepaisaxts_translator"]
