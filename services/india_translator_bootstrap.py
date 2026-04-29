"""v6 Phase 5-bis — India v2 translator startup activation.

Bootstraps the 30 India v2 broker translators into
:mod:`services.broker_translator_registry` based on the per-broker
``API_V2_<BROKER_CODE_UPPER>`` env flag.

Default behavior: every flag is OFF; no translator is registered;
the v2 dispatcher falls through to the legacy lane for India brokers
exactly as v5 Phase 9 left it. Operators flip individual brokers
to v2 by setting ``API_V2_<BROKER>=1`` and restarting the app.

Hooked into :func:`app.setup_environment` after
:func:`utils.plugin_loader.load_broker_capabilities`.
"""

from __future__ import annotations

import importlib
from typing import Iterable

from utils.feature_flags import is_enabled
from utils.logging import get_logger

logger = get_logger(__name__)


# (broker_code, install_fn_dotted_path)
INDIA_TRANSLATORS: list[tuple[str, str]] = [
    # Phase 5 (top-5 popularity)
    ("zerodha", "broker.zerodha.translator.install_zerodha_translator"),
    ("angel", "broker.angel.translator.install_angel_translator"),
    ("dhan", "broker.dhan.translator.install_dhan_translator"),
    ("upstox", "broker.upstox.translator.install_upstox_translator"),
    ("fyers", "broker.fyers.translator.install_fyers_translator"),
    # Phase 6 (alpha batch 1)
    ("aliceblue", "broker.aliceblue.translator.install_aliceblue_translator"),
    ("compositedge", "broker.compositedge.translator.install_compositedge_translator"),
    ("definedge", "broker.definedge.translator.install_definedge_translator"),
    ("firstock", "broker.firstock.translator.install_firstock_translator"),
    ("fivepaisa", "broker.fivepaisa.translator.install_fivepaisa_translator"),
    ("fivepaisaxts", "broker.fivepaisaxts.translator.install_fivepaisaxts_translator"),
    ("flattrade", "broker.flattrade.translator.install_flattrade_translator"),
    ("groww", "broker.groww.translator.install_groww_translator"),
    ("ibulls", "broker.ibulls.translator.install_ibulls_translator"),
    ("iifl", "broker.iifl.translator.install_iifl_translator"),
    ("iiflcapital", "broker.iiflcapital.translator.install_iiflcapital_translator"),
    ("indmoney", "broker.indmoney.translator.install_indmoney_translator"),
    # Phase 7 (alpha batch 2)
    ("jainamxts", "broker.jainamxts.translator.install_jainamxts_translator"),
    ("kotak", "broker.kotak.translator.install_kotak_translator"),
    ("motilal", "broker.motilal.translator.install_motilal_translator"),
    ("mstock", "broker.mstock.translator.install_mstock_translator"),
    ("nubra", "broker.nubra.translator.install_nubra_translator"),
    ("paytm", "broker.paytm.translator.install_paytm_translator"),
    ("pocketful", "broker.pocketful.translator.install_pocketful_translator"),
    ("rmoney", "broker.rmoney.translator.install_rmoney_translator"),
    ("samco", "broker.samco.translator.install_samco_translator"),
    ("shoonya", "broker.shoonya.translator.install_shoonya_translator"),
    ("tradejini", "broker.tradejini.translator.install_tradejini_translator"),
    ("wisdom", "broker.wisdom.translator.install_wisdom_translator"),
    ("zebu", "broker.zebu.translator.install_zebu_translator"),
]


def _resolve(dotted: str):
    module_path, _, name = dotted.rpartition(".")
    module = importlib.import_module(module_path)
    return getattr(module, name)


def _flag_name(broker_code: str) -> str:
    return f"API_V2_{broker_code.upper()}"


def is_translator_flag_on(broker_code: str) -> bool:
    """True iff ``API_V2_<BROKER>=1`` is set in the env."""
    return is_enabled(_flag_name(broker_code))


def install_enabled_india_translators(
    *, brokers: Iterable[tuple[str, str]] | None = None,
) -> list[str]:
    """Install translators for India brokers whose env flag is on.

    Returns the list of broker codes that were registered.

    Designed to be safe to call multiple times; re-registering a
    broker overwrites the prior entry per
    :func:`services.broker_translator_registry.register_broker_translator`.
    """
    table = list(brokers) if brokers is not None else INDIA_TRANSLATORS
    activated: list[str] = []
    for broker_code, install_path in table:
        if not is_translator_flag_on(broker_code):
            continue
        try:
            install_fn = _resolve(install_path)
            install_fn()
            activated.append(broker_code)
            logger.info(
                "v6 Phase 5-bis: installed v2 translator for %s (flag=%s)",
                broker_code, _flag_name(broker_code),
            )
        except Exception as e:
            # A broken broker plugin must not block app startup. The
            # broker's v1 lane is unaffected (no flag set ⇒ legacy).
            logger.exception(
                "v6 Phase 5-bis: failed to install v2 translator for %s: %s",
                broker_code, e,
            )
    return activated


def install_all_india_translators_for_tests() -> list[str]:
    """Install every India translator regardless of env flags.

    Test-only helper — production callers must use
    :func:`install_enabled_india_translators` so the operator's flag
    state is honored.
    """
    activated: list[str] = []
    for broker_code, install_path in INDIA_TRANSLATORS:
        try:
            install_fn = _resolve(install_path)
            install_fn()
            activated.append(broker_code)
        except Exception as e:
            logger.warning("install_all_india_translators_for_tests: %s failed: %s", broker_code, e)
    return activated


__all__ = [
    "INDIA_TRANSLATORS",
    "install_all_india_translators_for_tests",
    "install_enabled_india_translators",
    "is_translator_flag_on",
]
