"""Phase 3 v4 — India region plugin compliance harness invocation."""

from __future__ import annotations

from tests.compliance.region_plugin_compliance import RegionComplianceMixin


class TestIndiaRegionCompliance(RegionComplianceMixin):
    REGION_CODE = "india"
    STRICT = True
