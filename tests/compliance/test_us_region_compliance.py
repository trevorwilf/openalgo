"""Phase 3 v4 — US region plugin compliance harness invocation."""

from __future__ import annotations

from tests.compliance.region_plugin_compliance import RegionComplianceMixin


class TestUSRegionCompliance(RegionComplianceMixin):
    REGION_CODE = "us"
    STRICT = True
