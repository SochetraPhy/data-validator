"""
gatekeeper.checks
==================
Frictionless `Check` plugins for cross-field / business-logic rules that a
Table Schema alone can't express (schema.json handles per-column type,
required, unique, and pattern checks on its own -- these checks are only
for things that need to compare fields to each other or to a reference
list).

Every check below is a thin wrapper: it pulls the relevant cell(s) out of
the row, hands them to a pure function in `gatekeeper.rules`, and -- if
that function reports a problem -- yields a Frictionless error. The rule
code (e.g. "PROVINCE_UNKNOWN") is embedded in the error's `note` as a
`[RULE_CODE] message` prefix so validate.py can look it up in
`rules.RULE_SEVERITY` and decide whether it should block the gate (error)
or just be surfaced for review (warning).

See: https://framework.frictionlessdata.io/docs/guides/validating-data.html#custom-checks
"""
from __future__ import annotations

from frictionless import Check, errors

from . import rules


def _note(code: str, message: str) -> str:
    return f"[{code}] {message}"


class KhmerNameCheck(Check):
    """Factory Name (KM) should actually contain Khmer script."""

    Errors = [errors.CellError]

    def validate_row(self, row):
        result = rules.check_khmer_name(row.get("Factory Name (KM)"))
        if result is not None:
            code, message = result
            yield errors.CellError.from_row(row, note=_note(code, message), field_name="Factory Name (KM)")


class GeoPairCheck(Check):
    """Lat/Long must both be present or both blank, and fall inside Cambodia."""

    Errors = [errors.CellError]

    def validate_row(self, row):
        result = rules.check_geo_pair(row.get("Lat"), row.get("Long"))
        if result is not None:
            code, message = result
            yield errors.CellError.from_row(row, note=_note(code, message), field_name="Lat")


class ProvinceCheck(Check):
    """Province must be one of Cambodia's 25 provinces (alias-aware)."""

    Errors = [errors.CellError]

    def validate_row(self, row):
        result = rules.check_province(row.get("Province"))
        if result is not None:
            code, message = result
            yield errors.CellError.from_row(row, note=_note(code, message), field_name="Province")


class DateConsistencyCheck(Check):
    """Registered Date fields shouldn't be in the future or wildly disagree."""

    Errors = [errors.CellError]

    def validate_row(self, row):
        issues = rules.check_dates(row.get("Registered Date"), row.get("Registered Date (from MOC)"))
        for code, message, field in issues:
            yield errors.CellError.from_row(row, note=_note(code, message), field_name=field)


class OpenSupplyIdFormatCheck(Check):
    """Advisory structural check for the OS Hub ID shape."""

    Errors = [errors.CellError]

    def validate_row(self, row):
        result = rules.check_os_id(row.get("Open Supply ID"))
        if result is not None:
            code, message = result
            yield errors.CellError.from_row(row, note=_note(code, message), field_name="Open Supply ID")


class EmployeeCountCheck(Check):
    """Flags implausibly large headcounts for a human to double check."""

    Errors = [errors.CellError]

    def validate_row(self, row):
        result = rules.check_employee_count(row.get("Number of Employees"))
        if result is not None:
            code, message = result
            yield errors.CellError.from_row(row, note=_note(code, message), field_name="Number of Employees")


# Registered in this order so console/log output roughly follows column order.
ALL_CHECKS = [
    KhmerNameCheck,
    GeoPairCheck,
    ProvinceCheck,
    DateConsistencyCheck,
    OpenSupplyIdFormatCheck,
    EmployeeCountCheck,
]


def build_checks():
    """Instantiate every registered check. Kept as a function (rather than
    module-level instances) so each validation run gets fresh objects."""
    return [cls() for cls in ALL_CHECKS]
