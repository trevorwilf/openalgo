"""v6 Phase 5-bis — India translator bootstrap contract tests."""

from __future__ import annotations

import os
from unittest.mock import patch

import pytest

from services.broker_translator_registry import (
    clear_registry_for_tests,
    get_broker_translator,
)
from services.india_translator_bootstrap import (
    INDIA_TRANSLATORS,
    install_all_india_translators_for_tests,
    install_enabled_india_translators,
    is_translator_flag_on,
)


@pytest.fixture(autouse=True)
def _clean_registry():
    clear_registry_for_tests()
    yield
    clear_registry_for_tests()


def test_india_translators_table_has_30_entries() -> None:
    """All 30 India brokers from Phases 5/6/7 must be in the bootstrap table."""
    assert len(INDIA_TRANSLATORS) == 30


def test_india_translators_table_has_unique_broker_codes() -> None:
    codes = [bc for bc, _ in INDIA_TRANSLATORS]
    assert len(codes) == len(set(codes)), "duplicate broker_code in INDIA_TRANSLATORS"


@pytest.mark.parametrize("broker_code,install_path", INDIA_TRANSLATORS)
def test_install_path_resolves(broker_code: str, install_path: str) -> None:
    """Every install_fn dotted path must resolve to a callable."""
    import importlib

    module_path, _, name = install_path.rpartition(".")
    module = importlib.import_module(module_path)
    install_fn = getattr(module, name, None)
    assert callable(install_fn), (
        f"{install_path} not callable for broker {broker_code}"
    )


def test_no_translators_registered_when_no_flags_set(monkeypatch) -> None:
    """Default behavior: every API_V2_<BROKER> flag is unset; the
    bootstrap registers nothing."""
    # Clear any pre-existing flags
    for broker_code, _ in INDIA_TRANSLATORS:
        monkeypatch.delenv(f"API_V2_{broker_code.upper()}", raising=False)

    activated = install_enabled_india_translators()
    assert activated == []
    # And nothing is in the registry.
    for broker_code, _ in INDIA_TRANSLATORS:
        assert get_broker_translator(broker_code) is None


def test_only_flagged_brokers_are_activated(monkeypatch) -> None:
    """Setting API_V2_ZERODHA=1 + API_V2_ANGEL=1 activates exactly
    those two; other brokers stay unregistered."""
    for broker_code, _ in INDIA_TRANSLATORS:
        monkeypatch.delenv(f"API_V2_{broker_code.upper()}", raising=False)

    monkeypatch.setenv("API_V2_ZERODHA", "1")
    monkeypatch.setenv("API_V2_ANGEL", "1")

    activated = install_enabled_india_translators()
    assert set(activated) == {"zerodha", "angel"}

    assert get_broker_translator("zerodha") is not None
    assert get_broker_translator("angel") is not None
    # Other brokers stay unregistered.
    for broker_code, _ in INDIA_TRANSLATORS:
        if broker_code in {"zerodha", "angel"}:
            continue
        assert get_broker_translator(broker_code) is None, (
            f"{broker_code} unexpectedly registered without its flag"
        )


def test_falsy_flag_values_do_not_activate(monkeypatch) -> None:
    """API_V2_ZERODHA=0 / false / no should NOT activate."""
    for broker_code, _ in INDIA_TRANSLATORS:
        monkeypatch.delenv(f"API_V2_{broker_code.upper()}", raising=False)

    for falsy in ("0", "false", "no", "off", ""):
        monkeypatch.setenv("API_V2_ZERODHA", falsy)
        clear_registry_for_tests()
        activated = install_enabled_india_translators()
        assert "zerodha" not in activated, (
            f"zerodha unexpectedly activated for value {falsy!r}"
        )


def test_install_all_for_tests_registers_every_broker() -> None:
    """The test-only helper bypasses env flags and registers all 30."""
    activated = install_all_india_translators_for_tests()
    assert len(activated) == 30
    for broker_code, _ in INDIA_TRANSLATORS:
        translator = get_broker_translator(broker_code)
        assert translator is not None, f"{broker_code} not registered"
        assert translator.broker_code == broker_code


def test_is_translator_flag_on_helper(monkeypatch) -> None:
    monkeypatch.delenv("API_V2_ZERODHA", raising=False)
    assert is_translator_flag_on("zerodha") is False

    monkeypatch.setenv("API_V2_ZERODHA", "1")
    assert is_translator_flag_on("zerodha") is True

    monkeypatch.setenv("API_V2_ZERODHA", "0")
    assert is_translator_flag_on("zerodha") is False


def test_failed_install_does_not_block_other_brokers(monkeypatch) -> None:
    """If one broker's install fn raises, the bootstrap must continue
    and install the remaining flagged brokers."""
    # Set flags for two brokers; monkeypatch one to raise.
    for broker_code, _ in INDIA_TRANSLATORS:
        monkeypatch.delenv(f"API_V2_{broker_code.upper()}", raising=False)
    monkeypatch.setenv("API_V2_ZERODHA", "1")
    monkeypatch.setenv("API_V2_ANGEL", "1")

    # Make zerodha's install fn raise.
    import broker.zerodha.translator as zmod

    real_install = zmod.install_zerodha_translator

    def _broken_install():
        raise RuntimeError("synthetic test failure")

    with patch.object(zmod, "install_zerodha_translator", _broken_install):
        activated = install_enabled_india_translators()

    # Restore for downstream tests.
    zmod.install_zerodha_translator = real_install

    # Angel should still be registered despite Zerodha's failure.
    assert "angel" in activated
    assert get_broker_translator("angel") is not None
    # Zerodha should NOT be registered since its install fn raised.
    assert get_broker_translator("zerodha") is None
