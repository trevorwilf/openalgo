"""Phase 3 v4 — EU region plugin compliance harness invocation."""

from __future__ import annotations

from tests.compliance.region_plugin_compliance import RegionComplianceMixin


class TestEURegionCompliance(RegionComplianceMixin):
    REGION_CODE = "eu"
    STRICT = True
