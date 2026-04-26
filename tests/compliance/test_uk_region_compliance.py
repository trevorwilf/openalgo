"""Phase 3 v4 — UK region plugin compliance harness invocation."""

from __future__ import annotations

from tests.compliance.region_plugin_compliance import RegionComplianceMixin


class TestUKRegionCompliance(RegionComplianceMixin):
    REGION_CODE = "uk"
    STRICT = True
