"""Parity harness: Angel Broking (Smart API) v2 broker translator."""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any, Dict

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))
from tests.parity import _common  # noqa: E402,F401

from broker.angel.translator import AngelOrderTranslator  # noqa: E402
from tests.parity.baseline.parity_v2_india_common import (  # noqa: E402
    build_parity_output,
)

NAME = "parity_v2_angel_india"


def generate() -> Dict[str, Any]:
    return build_parity_output(
        name=NAME,
        translator_cls=AngelOrderTranslator,
        # Angel SmartAPI accept response
        sample_response={
            "data": {"orderid": "240319000123456"},
            "status": True,
        },
    )


if __name__ == "__main__":
    import json

    print(json.dumps(generate(), indent=2, sort_keys=True))
