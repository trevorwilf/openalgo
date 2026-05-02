"""Phase 0 (T-01) — region plugin v3 schema documentation gate.

The 10 v3 fields added to ``MarketRegion`` must be documented in
``docs/refactor/region-plugin-schema/`` so future plugin authors know
what each field is for. This test pins that contract.
"""

from __future__ import annotations

from pathlib import Path

import pytest


REPO_ROOT = Path(__file__).resolve().parents[2]
SCHEMA_DOC_ROOT = REPO_ROOT / "docs" / "refactor" / "region-plugin-schema"


REQUIRED_V3_FIELD_NAMES: tuple[str, ...] = (
    "product_vocabulary",
    "price_type_vocabulary",
    "mandatory_close_rules",
    "quantity_freeze_rules",
    "currency_locale",
    "option_grammar",
    "index_classification",
    "legacy_compat_shim",
    "screener_providers",
    "master_contract_refresh_policy",
)


def test_schema_doc_directory_exists() -> None:
    assert SCHEMA_DOC_ROOT.is_dir(), (
        f"Phase 0 must ship docs at {SCHEMA_DOC_ROOT.relative_to(REPO_ROOT)}"
    )


def test_v3_fields_doc_present_and_documents_every_field() -> None:
    v3_doc = SCHEMA_DOC_ROOT / "v3-fields.md"
    assert v3_doc.is_file(), f"missing {v3_doc.relative_to(REPO_ROOT)}"
    body = v3_doc.read_text(encoding="utf-8")
    missing = [name for name in REQUIRED_V3_FIELD_NAMES if name not in body]
    assert not missing, (
        f"v3-fields.md must mention every v3 field name; missing: {missing}"
    )


def test_readme_present_and_lists_v3_iteration() -> None:
    readme = SCHEMA_DOC_ROOT / "README.md"
    assert readme.is_file(), f"missing {readme.relative_to(REPO_ROOT)}"
    body = readme.read_text(encoding="utf-8")
    assert "v3" in body.lower(), "README must reference v3 schema iteration"
