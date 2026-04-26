"""v4 invariant 7 — advanced features (Sandbox, Options, Screener) are
provider-pluggable. Each has a generic contract and at least one
registered concrete provider.

* Phase 8 of v4 shipped the Sandbox provider contract + India + US.
* Phase 9 of v4 shipped the Options provider contract + India + US.
* Phase 10 of v4 shipped the Screener provider contract + India
  (Chartink). US screener provider is out of v4 scope (stub
  directory exists for future expansion).

All three sub-tests now pass; this is the regression net.
"""

from __future__ import annotations

from importlib import import_module
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]


SANDBOX_BASE_PATH = REPO_ROOT / "services" / "sandbox" / "providers" / "base.py"
SANDBOX_INDIA_PATH = REPO_ROOT / "services" / "sandbox" / "providers" / "india" / "__init__.py"
SANDBOX_US_PATH = REPO_ROOT / "services" / "sandbox" / "providers" / "us" / "__init__.py"

OPTIONS_BASE_PATH = REPO_ROOT / "services" / "options" / "providers" / "base.py"
OPTIONS_INDIA_PATH = REPO_ROOT / "services" / "options" / "providers" / "india" / "__init__.py"
OPTIONS_US_PATH = REPO_ROOT / "services" / "options" / "providers" / "us" / "__init__.py"

SCREENER_BASE_PATH = REPO_ROOT / "services" / "screeners" / "providers" / "base.py"
SCREENER_INDIA_PATH = REPO_ROOT / "services" / "screeners" / "providers" / "india" / "__init__.py"


def test_sandbox_provider_contract_exists_with_india_and_us_providers() -> None:
    assert SANDBOX_BASE_PATH.is_file(), (
        f"missing {SANDBOX_BASE_PATH.relative_to(REPO_ROOT).as_posix()} — "
        "Phase 8 of v4 ships the SandboxProvider Protocol."
    )
    assert SANDBOX_INDIA_PATH.is_file(), (
        f"missing {SANDBOX_INDIA_PATH.relative_to(REPO_ROOT).as_posix()} — "
        "Phase 8 of v4 ships the India sandbox provider."
    )
    assert SANDBOX_US_PATH.is_file(), (
        f"missing {SANDBOX_US_PATH.relative_to(REPO_ROOT).as_posix()} — "
        "Phase 8 of v4 ships the US sandbox provider."
    )
    base = import_module("services.sandbox.providers.base")
    assert hasattr(base, "SandboxProvider"), (
        "services.sandbox.providers.base must define SandboxProvider"
    )


def test_options_provider_contract_exists_with_india_and_us_providers() -> None:
    assert OPTIONS_BASE_PATH.is_file(), (
        f"missing {OPTIONS_BASE_PATH.relative_to(REPO_ROOT).as_posix()} — "
        "Phase 9 of v4 ships the OptionsProvider Protocol."
    )
    assert OPTIONS_INDIA_PATH.is_file(), (
        f"missing {OPTIONS_INDIA_PATH.relative_to(REPO_ROOT).as_posix()} — "
        "Phase 9 of v4 ships the India options provider."
    )
    assert OPTIONS_US_PATH.is_file(), (
        f"missing {OPTIONS_US_PATH.relative_to(REPO_ROOT).as_posix()} — "
        "Phase 9 of v4 ships the US options provider."
    )
    base = import_module("services.options.providers.base")
    assert hasattr(base, "OptionsProvider"), (
        "services.options.providers.base must define OptionsProvider"
    )


def test_screener_provider_contract_exists_with_india_provider() -> None:
    assert SCREENER_BASE_PATH.is_file(), (
        f"missing {SCREENER_BASE_PATH.relative_to(REPO_ROOT).as_posix()} — "
        "Phase 10 of v4 ships the ScreenerProvider Protocol."
    )
    assert SCREENER_INDIA_PATH.is_file(), (
        f"missing {SCREENER_INDIA_PATH.relative_to(REPO_ROOT).as_posix()} — "
        "Phase 10 of v4 ships the India (Chartink) screener provider."
    )
    base = import_module("services.screeners.providers.base")
    assert hasattr(base, "ScreenerProvider"), (
        "services.screeners.providers.base must define ScreenerProvider"
    )
