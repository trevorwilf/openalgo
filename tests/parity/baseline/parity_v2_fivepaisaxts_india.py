"""Parity harness: fivepaisaxts v2 broker translator."""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any, Dict

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))
from tests.parity import _common  # noqa: E402,F401

from broker.fivepaisaxts.translator import FivePaisaXTSOrderTranslator  # noqa: E402
from tests.parity.baseline.parity_v2_india_common import build_parity_output  # noqa: E402

NAME = "parity_v2_fivepaisaxts_india"


def generate() -> Dict[str, Any]:
    return build_parity_output(
        name=NAME, translator_cls=FivePaisaXTSOrderTranslator,
        sample_response={"result": {"AppOrderID": "240319000123456"}, "type": "success"},
    )


if __name__ == "__main__":
    import json
    print(json.dumps(generate(), indent=2, sort_keys=True))
