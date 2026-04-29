"""v6 Phase 6 — CompositeEdge v2 broker translator (XTS-family)."""

from __future__ import annotations

from broker._xts_family import XTSFamilyOrderTranslator

BROKER_CODE = "compositedge"


class CompositeEdgeOrderTranslator(XTSFamilyOrderTranslator):
    broker_code = BROKER_CODE


def install_compositedge_translator() -> CompositeEdgeOrderTranslator:
    from services.broker_translator_registry import register_broker_translator

    t = CompositeEdgeOrderTranslator()
    register_broker_translator(t)
    return t


__all__ = ["BROKER_CODE", "CompositeEdgeOrderTranslator", "install_compositedge_translator"]
