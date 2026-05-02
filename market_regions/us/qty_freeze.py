"""US quantity-freeze rules — Phase 7b T-30 build-out.

US equity / options markets do NOT have a regulator-published
per-instrument freeze table analogous to India's NFO ``qtyfreeze.csv``.
Position-size limits exist (PDT, Reg-T margin), but those are
account-level constraints rather than per-symbol order-quantity
caps.

This module exists to satisfy the
``MarketRegion.quantity_freeze_rules`` schema field with an explicit
empty list, documenting the absence rather than letting it default
implicitly.
"""

from __future__ import annotations

from typing import Any


QUANTITY_FREEZE_RULES: list[dict[str, Any]] = []


__all__ = ["QUANTITY_FREEZE_RULES"]
