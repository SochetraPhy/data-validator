"""
gatekeeper.messages
===================
Plain-language titles, explanations, and fix tips for every issue the
gatekeeper can raise -- both custom rule codes (PROVINCE_UNKNOWN, ...)
and native Frictionless schema errors (constraint-error, type-error, ...).

`validate.py` uses this to turn raw Frictionless notes into a readable
console report. The structured JSON log still keeps the original
`type` / `message` so downstream tools aren't broken.
"""
from __future__ import annotations

import re
from typing import Optional

# ---------------------------------------------------------------------------
# Custom rule codes (from gatekeeper/rules.py)
# ---------------------------------------------------------------------------
RULE_GUIDE = {
    "GEO_MISSING_PAIR": {
        "title": "Incomplete coordinates",
        "explain": "Latitude and longitude must both be filled in, or both left blank.",
        "fix": "Add the missing Lat or Long value, or clear both if the location is unknown.",
    },
    "GEO_OUT_OF_BOUNDS": {
        "title": "Coordinates outside Cambodia",
        "explain": "The Lat/Long pair falls outside Cambodia's approximate bounding box.",
        "fix": "Check for swapped Lat/Long, a mistyped digit, or a placeholder like 0,0.",
    },
    "PROVINCE_UNKNOWN": {
        "title": "Unknown province",
        "explain": "This value isn't one of Cambodia's 25 provinces/municipalities.",
        "fix": "Correct the spelling, or use the suggested closest match if one is shown.",
    },
    "PROVINCE_ALIAS": {
        "title": "Non-standard province name",
        "explain": "This looks like a known variant of a real province name.",
        "fix": "Replace it with the canonical province name shown in the message.",
    },
    "DATE_FUTURE": {
        "title": "Date is in the future",
        "explain": "A registration date cannot be later than today.",
        "fix": "Correct the year/month/day, or check that the column wasn't mis-mapped.",
    },
    "DATE_MISMATCH": {
        "title": "Registration dates disagree",
        "explain": "Registered Date and Registered Date (from MOC) differ by more than a year.",
        "fix": "Confirm which date is authoritative and align the other, or leave a note for review.",
    },
    "OS_ID_FORMAT": {
        "title": "Unusual Open Supply Hub ID",
        "explain": "The value doesn't match the expected 15-character OS Hub ID shape.",
        "fix": "Double-check the ID against Open Supply Hub. A mismatch isn't always wrong.",
    },
    "EMPLOYEE_COUNT_OUTLIER": {
        "title": "Unusually high employee count",
        "explain": "This headcount is much higher than typical for a single factory.",
        "fix": "Verify the number wasn't mistyped (extra zero) or aggregated across sites.",
    },
    "KM_NAME_NOT_KHMER": {
        "title": "Missing Khmer script",
        "explain": "Factory Name (KM) should contain Khmer characters, not only Latin text.",
        "fix": "Paste the Khmer name, or check that English/Khmer columns weren't swapped.",
    },
}

# ---------------------------------------------------------------------------
# Native Frictionless / schema error types
# ---------------------------------------------------------------------------
SCHEMA_GUIDE = {
    "constraint-error": {
        "title": "Value breaks a field rule",
        "explain": "The cell doesn't meet a schema constraint (required, pattern, min/max, …).",
        "fix": "Correct the value to match what the field expects.",
    },
    "type-error": {
        "title": "Wrong data type or format",
        "explain": "The cell couldn't be read as the type this column expects.",
        "fix": "Fix the format (e.g. a real email, YYYY-MM-DD date, or number).",
    },
    "unique-error": {
        "title": "Duplicate value",
        "explain": "This field must be unique across the file, but the same value appears twice.",
        "fix": "Give each row its own unique ID, or merge the duplicate rows.",
    },
    "required-error": {
        "title": "Required field missing",
        "explain": "This column is required but the cell is empty.",
        "fix": "Fill in the missing value.",
    },
    "extra-label": {
        "title": "Unexpected column",
        "explain": "The file has a column that isn't in the schema.",
        "fix": "Rename or remove the extra column, or update the schema if it's intentional.",
    },
    "missing-label": {
        "title": "Missing column",
        "explain": "A column required by the schema is absent from the file.",
        "fix": "Add the missing column header (and values), matching the schema name exactly.",
    },
    "blank-header": {
        "title": "Blank column header",
        "explain": "One of the header cells is empty.",
        "fix": "Give every column a non-empty header name.",
    },
    "duplicate-label": {
        "title": "Duplicate column header",
        "explain": "Two columns share the same header name.",
        "fix": "Rename one of the columns so every header is unique.",
    },
}

# Field-specific pattern hints (schema regexes are opaque to end users).
_FIELD_PATTERN_HINTS = {
    "Owner Phone": "Use a Cambodian number: 0XXXXXXXX / 0XXXXXXXXX, or +855XXXXXXXX / +855XXXXXXXXX.",
    "Contact Number": "Use a Cambodian number: 0XXXXXXXX / 0XXXXXXXXX, or +855XXXXXXXX / +855XXXXXXXXX.",
    "Google Maps": "Use a Google Maps URL (maps.google.com/... or maps.app.goo.gl/...).",
}

_FIELD_RANGE_HINTS = {
    "Lat": "Latitude for Cambodia is roughly 9 to 15 (north).",
    "Long": "Longitude for Cambodia is roughly 102 to 108 (east).",
    "Number of Employees": "Employee count must be 0 or greater.",
    "No": "Row number (No) must be a positive integer (1 or greater).",
}

_CELL_RE = re.compile(r'[Tt]he cell "([^"]*)"')
_CONSTRAINT_RE = re.compile(r'constraint "([^"]+)" is "([^"]*)"')
_UNIQUE_ROW_RE = re.compile(r"the same as in the row at position\s+(\d+)", re.I)
_TYPE_RE = re.compile(r'type is "([^"]+)"')


def guide_for(code: str) -> dict:
    """Return {title, explain, fix} for a rule or schema error code."""
    if code in RULE_GUIDE:
        return RULE_GUIDE[code]
    if code in SCHEMA_GUIDE:
        return SCHEMA_GUIDE[code]
    return {
        "title": code.replace("-", " ").replace("_", " ").title(),
        "explain": "A validation problem was found in this cell or row.",
        "fix": "Review the value and correct it to match the expected format.",
    }


def _extract_cell(message: str, note: str) -> Optional[str]:
    for text in (message, note):
        if not text:
            continue
        m = _CELL_RE.search(text)
        if m:
            return m.group(1)
    return None


def humanize_schema_issue(err_type: str, field: Optional[str], note: str, message: str):
    """Turn a native Frictionless schema error into (code, title, message, fix).

    `code` stays close to the Frictionless type (or a more specific subtype
    like `required-error` / `pattern-error`) so the JSON log stays greppable.
    """
    note = note or ""
    message = message or ""
    field = field or ""
    cell = _extract_cell(message, note)
    constraint = _CONSTRAINT_RE.search(note) or _CONSTRAINT_RE.search(message)

    if err_type == "constraint-error" and constraint:
        name, expected = constraint.group(1), constraint.group(2)
        if name == "required":
            return (
                "required-error",
                "Required field missing",
                f'"{field}" is required but this cell is empty.' if field else "A required cell is empty.",
                f'Enter a value for "{field}".' if field else "Fill in the missing value.",
            )
        if name == "pattern":
            shown = f'"{cell}"' if cell not in (None, "") else "This value"
            hint = _FIELD_PATTERN_HINTS.get(
                field,
                "Update the value so it matches the expected pattern for this field.",
            )
            return (
                "pattern-error",
                "Value doesn't match the expected pattern",
                f'{shown} in "{field}" is not in the accepted format.',
                hint,
            )
        if name in ("minimum", "maximum", "minLength", "maxLength"):
            shown = f'"{cell}"' if cell is not None else "This value"
            bound = "at least" if name in ("minimum", "minLength") else "at most"
            unit = "characters" if "Length" in name else ""
            detail = f"{bound} {expected} {unit}".strip()
            hint = _FIELD_RANGE_HINTS.get(
                field,
                f'Adjust "{field}" so it is {detail}.',
            )
            return (
                "range-error",
                "Value outside allowed range",
                f'{shown} in "{field}" is outside the allowed range ({detail}).',
                hint,
            )
        if name == "enum":
            shown = f'"{cell}"' if cell is not None else "This value"
            return (
                "enum-error",
                "Value not in allowed list",
                f'{shown} is not one of the allowed values for "{field}".',
                f'Pick a value from the allowed list for "{field}".',
            )

    if err_type == "unique-error":
        dup = _UNIQUE_ROW_RE.search(note) or _UNIQUE_ROW_RE.search(message)
        other = f" (same as row {dup.group(1)})" if dup else ""
        return (
            "unique-error",
            "Duplicate value",
            f'"{field}" must be unique, but this value already appears elsewhere{other}.',
            f'Give this row a unique "{field}", or remove/merge the duplicate.',
        )

    if err_type == "type-error":
        type_m = _TYPE_RE.search(note) or _TYPE_RE.search(message)
        type_label = type_m.group(1) if type_m else "the expected type"
        shown = f'"{cell}"' if cell is not None else "This value"
        friendly = {
            "string/email": "a valid email address (name@example.com)",
            "string/uri": "a valid URL (https://...)",
            "date": "a date in YYYY-MM-DD form",
            "integer": "a whole number",
            "number": "a number",
            "string": "text",
            "boolean": "true/false",
        }.get(type_label, type_label)
        return (
            "type-error",
            "Wrong data type or format",
            f'{shown} in "{field}" could not be read as {friendly}.',
            f'Change the value so it looks like {friendly}.',
        )

    guide = guide_for(err_type)
    # Fall back to the (often verbose) Frictionless message, trimmed.
    fallback = message or note or guide["explain"]
    return err_type, guide["title"], fallback, guide["fix"]


def enrich_issue(issue: dict) -> dict:
    """Add title / explain / fix onto an already-classified issue dict."""
    code = issue.get("type") or "error"
    if code in RULE_GUIDE:
        guide = RULE_GUIDE[code]
        issue["title"] = guide["title"]
        issue["explain"] = issue.get("message") or guide["explain"]
        issue["fix"] = guide["fix"]
        return issue

    # Native / already-humanized schema codes
    if code in SCHEMA_GUIDE or code in (
        "required-error", "pattern-error", "range-error", "enum-error",
    ):
        # Prefer fields already set by humanize_schema_issue
        if "title" in issue and "fix" in issue:
            issue.setdefault("explain", issue.get("message") or "")
            return issue
        guide = guide_for(code)
        issue["title"] = guide["title"]
        issue["explain"] = issue.get("message") or guide["explain"]
        issue["fix"] = guide["fix"]
        return issue

    guide = guide_for(code)
    issue["title"] = guide["title"]
    issue["explain"] = issue.get("message") or guide["explain"]
    issue["fix"] = guide["fix"]
    return issue
