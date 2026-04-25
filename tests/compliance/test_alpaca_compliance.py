"""Phase 7 — Alpaca compliance harness invocation.

Runs every contract in :class:`BrokerComplianceMixin` against the
shipped Alpaca plugin. Failures here block the merge — Alpaca is the
reference implementation for the promoted lane.
"""

from __future__ import annotations

from tests.compliance.broker_plugin_compliance import BrokerComplianceMixin


class TestAlpacaCompliance(BrokerComplianceMixin):
    BROKER_CODE = "alpaca"
    STRICT = True
