"""Reference sync adapters for Phase 2b.

The `ADAPTERS` registry maps broker_code → adapter class. The login
path in `utils/auth_utils.py` reads this dict when ``INSTRUMENT_CORE_V2``
is enabled to decide whether a given broker has a Phase 2b adapter.
Brokers not in this dict continue to use only the legacy master-contract
download path.

Keep the adapter list small and intentional — every added adapter is a
fresh consumer of `database.instruments_repo` and needs its own tests
and sample fixtures.
"""

from __future__ import annotations

from services.instrument_sync_adapters.alpaca_adapter import AlpacaAdapter
from services.instrument_sync_adapters.delta_adapter import DeltaAdapter
from services.instrument_sync_adapters.zerodha_adapter import ZerodhaAdapter

ADAPTERS = {
    "zerodha": ZerodhaAdapter,
    "deltaexchange": DeltaAdapter,
    "alpaca": AlpacaAdapter,
}


__all__ = ["ADAPTERS", "AlpacaAdapter", "DeltaAdapter", "ZerodhaAdapter"]
