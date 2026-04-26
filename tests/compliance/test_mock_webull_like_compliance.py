"""Phase 6 v3 — broker compliance harness invocation for the
mock Webull-LIKE plugin.
"""

from __future__ import annotations

from tests.compliance.broker_plugin_compliance import BrokerComplianceMixin


class TestMockWebullLikeCompliance(BrokerComplianceMixin):
    BROKER_CODE = "_mock_webull_like"
    STRICT = True
