"""Parity harness: groww v2 broker translator."""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any, Dict

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))
from tests.parity import _common  # noqa: E402,F401

from broker.groww.translator import GrowwOrderTranslator  # noqa: E402
from tests.parity.baseline.parity_v2_india_common import build_parity_output  # noqa: E402

NAME = "parity_v2_groww_india"


def generate() -> Dict[str, Any]:
    return build_parity_output(
        name=NAME, translator_cls=GrowwOrderTranslator,
        sample_response={"groww_order_id": "240319000123456", "order_status": "NEW"},
    )


if __name__ == "__main__":
    import json
    print(json.dumps(generate(), indent=2, sort_keys=True))
