"""Phase 6 v3 — broker compliance harness invocation for the
mock Schwab-LIKE plugin.

Exercises every contract in :class:`BrokerComplianceMixin` against
the in-memory mock plugin. Failures here surface framework gaps —
not real Schwab API issues, since this plugin is fully synthetic.
"""

from __future__ import annotations

from tests.compliance.broker_plugin_compliance import BrokerComplianceMixin


class TestMockSchwabLikeCompliance(BrokerComplianceMixin):
    BROKER_CODE = "_mock_schwab_like"
    STRICT = True
