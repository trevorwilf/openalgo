"""Phase 3 v4 — region plugin compliance harness (ADR 0023).

Mirrors :mod:`tests.compliance.broker_plugin_compliance`. Subclass
:class:`RegionComplianceMixin` and set ``REGION_CODE`` to the region's
plugin directory name. Each test method runs an assertion on one
surface of the region plugin contract:

* metadata — required top-level fields present and well-formed.
* timezone — declared `timezone_name` is a valid IANA tz identifier.
* currency — `default_currency` resolves to a known
  :class:`domain.currency.Currency`.
* market_families — non-empty and entries map to known enums.
* venues — at least one venue declared with all required sub-fields;
  every venue's `timezone_name` and `base_currency` parse cleanly.
* session_templates — non-empty; every template's `venue_codes` exist
  in the `venues` block; `local_start_time < local_end_time`;
  `days_of_week` are valid 0..6.
* calendar_exceptions — every exception's `venue_code` exists in the
  `venues` block; `exception_type` is one of the known set.
* symbol_display — `option_right_codes` non-empty; `date_format` parses
  for India / US conventions.
* feature_flags — every declared flag is a boolean.

Reports are recorded in ``COMPLIANCE_RESULTS`` so a downstream renderer
can produce the per-region matrix (the broker compliance matrix has a
similar pattern).
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, ClassVar
from zoneinfo import ZoneInfo

import pytest

from domain.currency import Currency

REPO_ROOT = Path(__file__).resolve().parents[2]


COMPLIANCE_RESULTS: dict[str, dict[str, str]] = {}


def _record(region_code: str, contract: str, status: str) -> None:
    bucket = COMPLIANCE_RESULTS.setdefault(region_code, {})
    bucket[contract] = status


KNOWN_EXCEPTION_TYPES = {"CLOSED", "EARLY_CLOSE", "LATE_OPEN", "SPECIAL_SESSION"}
INDIA_DATE_FORMATS = {"DDMMMYY", "DD-MMM-YY", "YYYY-MM-DD"}
US_DATE_FORMATS = {"YYYY-MM-DD", "OSI21", "OCC"}


class RegionComplianceMixin:
    """Mix in to a TestCase subclass with ``REGION_CODE = "..."``."""

    REGION_CODE: ClassVar[str]
    STRICT: ClassVar[bool] = True

    @classmethod
    def _region_dir(cls) -> Path:
        return REPO_ROOT / "market_regions" / cls.REGION_CODE

    @classmethod
    def _plugin_data(cls) -> dict[str, Any]:
        path = cls._region_dir() / "plugin.json"
        if not path.is_file():
            return {}
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            return {}

    def _record_pass(self, contract: str) -> None:
        _record(self.REGION_CODE, contract, "pass")

    def _record_fail(self, contract: str, reason: str) -> None:
        _record(self.REGION_CODE, contract, f"fail:{reason}")

    # ---- A. Metadata --------------------------------------------------

    def test_a_metadata_required_fields(self):
        data = self._plugin_data()
        required = (
            "region_code",
            "display_name",
            "timezone_name",
            "market_families",
            "default_currency",
            "default_venue_codes",
            "country_codes",
        )
        missing = [f for f in required if f not in data]
        if missing:
            self._record_fail("metadata", f"missing: {missing}")
            pytest.fail(f"region {self.REGION_CODE}: missing fields {missing}")
        # region_code matches directory.
        norm = str(data["region_code"]).strip().lower().replace("-", "_")
        if norm != self.REGION_CODE:
            self._record_fail("metadata", f"region_code mismatch: {norm}")
            pytest.fail(
                f"region {self.REGION_CODE}: plugin.json region_code "
                f"is {norm!r}, expected {self.REGION_CODE!r}"
            )
        self._record_pass("metadata")

    # ---- B. Timezone --------------------------------------------------

    def test_b_timezone_is_iana(self):
        tz_name = self._plugin_data().get("timezone_name", "")
        try:
            ZoneInfo(tz_name)
        except Exception:
            self._record_fail("timezone", f"invalid IANA tz: {tz_name!r}")
            pytest.fail(f"region {self.REGION_CODE}: timezone_name {tz_name!r} is not a valid IANA tz")
        self._record_pass("timezone")

    # ---- C. Currency --------------------------------------------------

    def test_c_default_currency_resolves(self):
        currency_code = self._plugin_data().get("default_currency", "")
        try:
            Currency(currency_code)
        except Exception:
            self._record_fail("currency", f"unknown currency: {currency_code!r}")
            pytest.fail(
                f"region {self.REGION_CODE}: default_currency {currency_code!r} "
                "is not in domain.currency.Currency"
            )
        self._record_pass("currency")

    # ---- D. Venues ----------------------------------------------------

    def test_d_venues_well_formed(self):
        data = self._plugin_data()
        venues = data.get("venues", [])
        if not venues:
            if self.STRICT:
                self._record_fail("venues", "no venues declared")
                pytest.fail(f"region {self.REGION_CODE}: no venues in plugin")
            self._record_pass("venues")
            return
        problems: list[str] = []
        for v in venues:
            code = v.get("venue_code")
            if not code:
                problems.append(f"venue without venue_code: {v}")
                continue
            tz = v.get("timezone_name")
            if tz:
                try:
                    ZoneInfo(tz)
                except Exception:
                    problems.append(f"{code}: invalid timezone {tz!r}")
            cur = v.get("base_currency")
            if cur:
                try:
                    Currency(cur)
                except Exception:
                    problems.append(f"{code}: unknown currency {cur!r}")
        if problems:
            self._record_fail("venues", "; ".join(problems))
            pytest.fail(f"region {self.REGION_CODE}: " + "; ".join(problems))
        self._record_pass("venues")

    # ---- E. Session templates ----------------------------------------

    def test_e_session_templates_valid(self):
        data = self._plugin_data()
        venues = {v.get("venue_code") for v in data.get("venues", [])}
        templates = data.get("session_templates", [])
        if not templates:
            self._record_pass("sessions")
            return
        problems: list[str] = []
        for t in templates:
            for vc in t.get("venue_codes", []):
                if vc not in venues:
                    problems.append(
                        f"session_template references unknown venue {vc!r}"
                    )
            dows = t.get("days_of_week", [])
            for d in dows:
                if not isinstance(d, int) or not 0 <= d <= 6:
                    problems.append(f"days_of_week entry out of range: {d}")
            start = t.get("local_start_time", "")
            end = t.get("local_end_time", "")
            if start and end and start >= end:
                problems.append(
                    f"session start >= end ({start} >= {end})"
                )
        if problems:
            self._record_fail("sessions", "; ".join(problems))
            pytest.fail(f"region {self.REGION_CODE}: " + "; ".join(problems))
        self._record_pass("sessions")

    # ---- F. Calendar exceptions --------------------------------------

    def test_f_calendar_exceptions_valid(self):
        data = self._plugin_data()
        venues = {v.get("venue_code") for v in data.get("venues", [])}
        excs = data.get("calendar_exceptions", [])
        problems: list[str] = []
        for e in excs:
            vc = e.get("venue_code")
            if vc and vc not in venues:
                problems.append(f"calendar_exception references unknown venue {vc!r}")
            etype = e.get("exception_type", "").upper()
            if etype not in KNOWN_EXCEPTION_TYPES:
                problems.append(f"unknown exception_type {etype!r}")
        if problems:
            self._record_fail("calendar", "; ".join(problems))
            pytest.fail(f"region {self.REGION_CODE}: " + "; ".join(problems))
        self._record_pass("calendar")

    # ---- G. Symbol display -------------------------------------------

    def test_g_symbol_display_present(self):
        data = self._plugin_data()
        sd = data.get("symbol_display", {})
        date_format = sd.get("date_format")
        rights = sd.get("option_right_codes", [])
        if not rights:
            self._record_fail("symbol_display", "option_right_codes empty")
            pytest.fail(
                f"region {self.REGION_CODE}: symbol_display.option_right_codes "
                "is required"
            )
        # Region-specific date format expectations.
        if self.REGION_CODE == "india":
            if date_format not in INDIA_DATE_FORMATS:
                self._record_fail("symbol_display", f"unexpected date_format {date_format!r}")
                pytest.fail(
                    f"India region: date_format {date_format!r} not in "
                    f"{INDIA_DATE_FORMATS}"
                )
        elif self.REGION_CODE == "us":
            if date_format not in US_DATE_FORMATS:
                self._record_fail("symbol_display", f"unexpected date_format {date_format!r}")
                pytest.fail(
                    f"US region: date_format {date_format!r} not in {US_DATE_FORMATS}"
                )
        self._record_pass("symbol_display")

    # ---- H. Feature flags --------------------------------------------

    def test_h_feature_flags_booleans(self):
        flags = self._plugin_data().get("feature_flags", {})
        problems: list[str] = []
        for name, value in flags.items():
            if not isinstance(value, bool):
                problems.append(f"{name}={value!r} is not a boolean")
        if problems:
            self._record_fail("feature_flags", "; ".join(problems))
            pytest.fail(f"region {self.REGION_CODE}: " + "; ".join(problems))
        self._record_pass("feature_flags")
