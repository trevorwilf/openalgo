"""Phase 3 v6 — chart metadata multi-region smoke test.

Verifies that for each region's representative venue, the chart
metadata available via the venue session service / region plugin
carries:

* Region-correct timezone (e.g., Asia/Kolkata for India,
  America/New_York for US, Europe/Paris for EU, Europe/London for UK).
* Region-correct currency (INR / USD / EUR / GBP).
* Region-correct session windows.

This is the framework-level check that chart rendering can compose
its metadata from region data, not from India literals.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
REGION_ROOT = REPO_ROOT / "market_regions"


@pytest.mark.parametrize(
    ("region_code", "venue_code", "expected_tz"),
    [
        ("india", "NSE", "Asia/Kolkata"),
        ("us", "XNYS", "America/New_York"),
        ("eu", "XPAR", "Europe/Paris"),
        ("uk", "XLON", "Europe/London"),
    ],
)
def test_venue_timezone_matches_region(
    region_code: str, venue_code: str, expected_tz: str,
) -> None:
    """Each region's representative venue must declare the expected
    IANA timezone. Chart formatting reads from this — never from a
    literal `Asia/Kolkata` outside the India region plugin."""
    p = REGION_ROOT / region_code / "plugin.json"
    data = json.loads(p.read_text(encoding="utf-8"))
    by_code = {v["venue_code"]: v for v in data.get("venues", [])}
    assert venue_code in by_code, (
        f"region {region_code!r} has no venue {venue_code!r}"
    )
    assert by_code[venue_code]["timezone_name"] == expected_tz


@pytest.mark.parametrize(
    ("region_code", "expected_currency"),
    [("india", "INR"), ("us", "USD"), ("eu", "EUR"), ("uk", "GBP")],
)
def test_venue_currency_matches_region(
    region_code: str, expected_currency: str,
) -> None:
    p = REGION_ROOT / region_code / "plugin.json"
    data = json.loads(p.read_text(encoding="utf-8"))
    for venue in data.get("venues", []):
        assert venue["base_currency"] == expected_currency, (
            f"venue {venue['venue_code']} in region {region_code!r} declares "
            f"base_currency={venue['base_currency']!r}; expected "
            f"{expected_currency!r}"
        )


@pytest.mark.parametrize(
    ("region_code", "expected_session_label"),
    [
        ("india", "REGULAR"),
        ("us", "REGULAR"),
        ("eu", "REGULAR"),
        ("uk", "REGULAR"),
    ],
)
def test_each_region_declares_a_regular_session(
    region_code: str, expected_session_label: str,
) -> None:
    """Every region must declare at least one ``REGULAR`` session in
    its session_templates — chart rendering needs at minimum a
    regular open/close window."""
    p = REGION_ROOT / region_code / "plugin.json"
    data = json.loads(p.read_text(encoding="utf-8"))
    codes = {s.get("session_code") for s in data.get("session_templates", [])}
    assert expected_session_label in codes, (
        f"region {region_code!r} session_templates missing "
        f"{expected_session_label!r}; got {sorted(codes)}"
    )
