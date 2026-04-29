"""v6 Phase 6 — IIFL v2 broker translator (XTS-family)."""

from __future__ import annotations

from broker._xts_family import XTSFamilyOrderTranslator

BROKER_CODE = "iifl"


class IIFLOrderTranslator(XTSFamilyOrderTranslator):
    broker_code = BROKER_CODE


def install_iifl_translator() -> IIFLOrderTranslator:
    from services.broker_translator_registry import register_broker_translator

    t = IIFLOrderTranslator()
    register_broker_translator(t)
    return t


__all__ = ["BROKER_CODE", "IIFLOrderTranslator", "install_iifl_translator"]
