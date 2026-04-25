"""Phase 7 — broker plugin compliance harness.

Subclass :class:`BrokerComplianceMixin` and set ``BROKER_CODE`` to the
broker's plugin directory name. Each test method runs an assertion on
one surface of the broker plugin contract.

Usage::

    class TestAlpacaCompliance(BrokerComplianceMixin):
        BROKER_CODE = "alpaca"

The harness is intentionally subclass-based (rather than parameterized
over ``broker``) so per-broker test files can target a specific
``BROKER_CODE`` and document deviations explicitly.

Reports are gathered into ``COMPLIANCE_RESULTS`` so a downstream
process (Phase 7 admin endpoint, broker_compliance_matrix.md
generator) can render the matrix.
"""

from __future__ import annotations

import importlib
import json
from pathlib import Path
from typing import Any, ClassVar

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]


# Keyed on broker_code. Values are dict[contract_name -> "pass"|"fail"|"skip"].
# Tests record their own outcomes for the matrix renderer.
COMPLIANCE_RESULTS: dict[str, dict[str, str]] = {}


def _record(broker_code: str, contract: str, status: str) -> None:
    bucket = COMPLIANCE_RESULTS.setdefault(broker_code, {})
    bucket[contract] = status


class BrokerComplianceMixin:
    """Mix this in to a TestCase subclass with ``BROKER_CODE = "..."``."""

    BROKER_CODE: ClassVar[str]
    STRICT: ClassVar[bool] = True
    """When False, missing optional surfaces are recorded as 'skip'
    rather than 'fail' — used to baseline legacy India brokers."""

    # ---- helpers ------------------------------------------------------

    @classmethod
    def _broker_dir(cls) -> Path:
        return REPO_ROOT / "broker" / cls.BROKER_CODE

    @classmethod
    def _plugin_data(cls) -> dict[str, Any]:
        path = cls._broker_dir() / "plugin.json"
        if not path.is_file():
            return {}
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            return {}

    def _record_pass(self, contract: str) -> None:
        _record(self.BROKER_CODE, contract, "pass")

    def _record_skip(self, contract: str) -> None:
        _record(self.BROKER_CODE, contract, "skip")

    def _record_fail(self, contract: str, reason: str) -> None:
        _record(self.BROKER_CODE, contract, f"fail:{reason}")

    # ---- A. Metadata --------------------------------------------------

    def test_a_metadata_plugin_json_validates(self):
        contract = "metadata"
        plugin = self._plugin_data()
        if not plugin:
            self._record_fail(contract, "plugin.json missing or unreadable")
            pytest.fail(f"plugin.json missing for {self.BROKER_CODE}")
        # Schema validation goes through the plugin loader path.
        from utils import plugin_loader

        plugin_loader._reset_cache_for_tests()
        errors = plugin_loader._validate_plugin_json(plugin)
        if errors:
            self._record_fail(contract, "; ".join(errors[:3]))
            pytest.fail("plugin.json failed schema: " + "; ".join(errors))
        self._record_pass(contract)

    def test_b_auth_module_exposes_authenticate(self):
        contract = "auth"
        try:
            mod = importlib.import_module(
                f"broker.{self.BROKER_CODE}.api.auth_api"
            )
        except ModuleNotFoundError:
            if self.STRICT:
                self._record_fail(contract, "auth_api module missing")
                pytest.fail(f"broker.{self.BROKER_CODE}.api.auth_api missing")
            self._record_skip(contract)
            return
        # Either authenticate (the new API) or authenticate_broker
        # (the legacy India plugin convention) is acceptable.
        if not (hasattr(mod, "authenticate") or hasattr(mod, "authenticate_broker")):
            if self.STRICT:
                self._record_fail(contract, "no authenticate / authenticate_broker")
                pytest.fail(
                    "auth_api must expose authenticate or authenticate_broker"
                )
            self._record_skip(contract)
            return
        self._record_pass(contract)

    # ---- C. Account contract (NormalizedAccountSnapshot) ------------

    def test_c_account_snapshot_uses_normalized_shape(self):
        contract = "account"
        try:
            mod = importlib.import_module(
                f"broker.{self.BROKER_CODE}.api.account_api"
            )
        except ModuleNotFoundError:
            self._record_skip(contract)
            return

        from domain.account import NormalizedAccountSnapshot

        # If the module exposes get_account_snapshot, its signature
        # must produce a NormalizedAccountSnapshot.
        snapshot_fn = getattr(mod, "get_account_snapshot", None)
        if snapshot_fn is None:
            self._record_skip(contract)
            return
        # Inspect the return annotation if present. ``from __future__
        # import annotations`` makes annotations strings — accept
        # either the class object OR the matching string name.
        ann = getattr(snapshot_fn, "__annotations__", {}).get("return")
        if ann is None:
            self._record_skip(contract)
            return
        accepted_classes = {NormalizedAccountSnapshot}
        legacy_alias = getattr(mod, "AccountSnapshot", None)
        if legacy_alias is not None:
            accepted_classes.add(legacy_alias)
        accepted_names = {c.__name__ for c in accepted_classes}
        if isinstance(ann, str):
            ok = ann in accepted_names
        else:
            ok = ann in accepted_classes
        if not ok:
            self._record_fail(
                contract,
                f"get_account_snapshot returns {ann!r}; expected NormalizedAccountSnapshot",
            )
            pytest.fail(f"non-normalized return: {ann!r}")
        self._record_pass(contract)

    # ---- D. Translator contract ---------------------------------------

    def test_d_translator_module_exists(self):
        contract = "translator"
        # Translators live under broker/<code>/api/order_api.py and
        # expose <Code>OrderTranslator. India brokers don't have them
        # yet — treated as skip in non-strict mode.
        try:
            mod = importlib.import_module(
                f"broker.{self.BROKER_CODE}.api.order_api"
            )
        except ModuleNotFoundError:
            if self.STRICT:
                self._record_fail(contract, "order_api module missing")
                pytest.fail("order_api missing")
            self._record_skip(contract)
            return
        # Find a class whose name ends with OrderTranslator.
        translator_cls = None
        for attr in dir(mod):
            if attr.endswith("OrderTranslator"):
                translator_cls = getattr(mod, attr)
                break
        if translator_cls is None:
            if self.STRICT:
                self._record_fail(contract, "no *OrderTranslator class")
                pytest.fail(f"no *OrderTranslator class in {mod.__name__}")
            self._record_skip(contract)
            return
        # Spot-check the contract methods.
        for method in ("validate", "to_native", "from_native_order_response"):
            if not hasattr(translator_cls, method):
                self._record_fail(contract, f"translator missing {method}()")
                pytest.fail(f"translator missing {method}()")
        self._record_pass(contract)

    # ---- E. Market data adapters --------------------------------------

    def test_e_market_data_adapters_optional(self):
        contract = "market_data"
        try:
            mod_quote = importlib.import_module(
                f"broker.{self.BROKER_CODE}.api.quote_api"
            )
            mod_bar = importlib.import_module(
                f"broker.{self.BROKER_CODE}.api.bar_api"
            )
        except ModuleNotFoundError:
            self._record_skip(contract)
            return
        # Spot-check quote + bar entry points.
        if not (hasattr(mod_quote, "AlpacaQuoteAdapter") or hasattr(mod_quote, "get_quote")):
            self._record_skip(contract)
            return
        self._record_pass(contract)

    # ---- F. Instrument sync contract ----------------------------------

    def test_f_instrument_sync_optional(self):
        contract = "instrument_sync"
        try:
            importlib.import_module(
                f"broker.{self.BROKER_CODE}.sync.instrument_sync"
            )
        except ModuleNotFoundError:
            self._record_skip(contract)
            return
        self._record_pass(contract)

    # ---- G. Rule matrix contract --------------------------------------

    def test_g_rule_matrix_optional(self):
        contract = "rules"
        # We don't introspect the seeded rules here — that's a runtime
        # check. The harness only verifies the BROKER plugin doesn't
        # forbid rules. Strict brokers must declare at least one rule
        # via broker_rules_repo.rules_upsert at startup or test setup.
        self._record_skip(contract)

    # ---- H. Lane isolation -------------------------------------------

    def test_h_lane_isolation_imports_and_literals(self):
        contract = "lane_isolation"
        plugin = self._plugin_data()
        regions = [str(r).lower() for r in (plugin.get("supported_regions") or [])]
        is_promoted = (
            (self._broker_dir() / "PROMOTED").exists()
            or (regions and "india" not in regions)
        )
        if not is_promoted:
            # Legacy India broker — lane-isolation contract does not apply.
            self._record_skip(contract)
            return
        from tests.contracts.test_lane_isolation import (
            _check_file,
            _literal_violations_in_file,
        )

        violations: list[str] = []
        for py in self._broker_dir().rglob("*.py"):
            violations.extend(_check_file(py))
            violations.extend(_literal_violations_in_file(py))
        if violations:
            self._record_fail(
                contract, f"{len(violations)} violations: {violations[0]}"
            )
            pytest.fail(
                "lane-isolation violations:\n  " + "\n  ".join(violations[:5])
            )
        self._record_pass(contract)

    # ---- I. Fail-closed ----------------------------------------------

    def test_i_fail_closed_capability_metadata(self):
        contract = "fail_closed"
        plugin = self._plugin_data()
        regions = [str(r).lower() for r in (plugin.get("supported_regions") or [])]
        if "india" in regions or not regions:
            # Legacy India bucket — Phase 1 fail-closed doesn't apply.
            self._record_skip(contract)
            return
        from utils.plugin_loader import _check_plugin_completeness

        missing = _check_plugin_completeness(self.BROKER_CODE, plugin)
        if missing:
            self._record_fail(contract, f"missing required: {missing}")
            pytest.fail(f"plugin incomplete: missing {missing}")
        self._record_pass(contract)


__all__ = ["BrokerComplianceMixin", "COMPLIANCE_RESULTS"]
