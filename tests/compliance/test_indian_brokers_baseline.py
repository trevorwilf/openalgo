"""Phase 7 — non-strict baseline compliance for Indian brokers.

Runs the contract in non-strict mode against representative legacy
India broker plugins. The point isn't to fail the build — it's to
build an observable baseline (``COMPLIANCE_RESULTS``) the matrix
renderer reads. Most fields are exempted as ``skip`` because legacy
India brokers are tied to the legacy lane and intentionally do not
implement the new translator/account/sync surfaces.
"""

from __future__ import annotations

import pytest

from tests.compliance.broker_plugin_compliance import BrokerComplianceMixin


class TestZerodhaBaseline(BrokerComplianceMixin):
    BROKER_CODE = "zerodha"
    STRICT = False


class TestDhanBaseline(BrokerComplianceMixin):
    BROKER_CODE = "dhan"
    STRICT = False


class TestDeltaExchangeBaseline(BrokerComplianceMixin):
    BROKER_CODE = "deltaexchange"
    STRICT = False
