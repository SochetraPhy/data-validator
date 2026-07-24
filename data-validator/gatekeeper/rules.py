"""
gatekeeper.rules
================
Pure-Python validation rules for the Cambodia factory-registry gatekeeper.

Nothing in this file imports `frictionless`. Every function takes plain
values (str / int / float / datetime.date / None) and returns either:

    None                          -> no problem
    (RULE_CODE, message)          -> a problem
    (RULE_CODE, message, field)   -> a problem tied to a specific field
                                      (only used by check_dates, which can
                                      flag either date column)

Keeping the logic here, instead of inside the Frictionless Check classes,
means it can be unit-tested directly (see tests at the bottom of this file,
run with `python -m gatekeeper.rules`) without needing frictionless
installed at all. `gatekeeper/checks.py` wraps these functions as
Frictionless Check plugins.

RULE_SEVERITY controls whether an issue blocks the gate ("error") or is
just surfaced for human review ("warning"). Anything Frictionless raises
natively from the schema (type-error, required-error, pattern-constraint,
unique-error, ...) is NOT in this dict and is always treated as "error" --
see validate.py.
"""
from __future__ import annotations

import datetime
import re
from difflib import get_close_matches
from typing import Optional, Union

# ---------------------------------------------------------------------------
# Severity table for the *custom* rules below. Native schema errors are
# always "error" and are not listed here.
# ---------------------------------------------------------------------------
RULE_SEVERITY = {
    "GEO_MISSING_PAIR": "error",
    "GEO_OUT_OF_BOUNDS": "error",
    "PROVINCE_UNKNOWN": "error",
    "PROVINCE_ALIAS": "warning",
    "DATE_FUTURE": "error",
    "DATE_MISMATCH": "warning",
    "OS_ID_FORMAT": "warning",
    "EMPLOYEE_COUNT_OUTLIER": "warning",
    "KM_NAME_NOT_KHMER": "warning",
}

# ---------------------------------------------------------------------------
# Reference data
# ---------------------------------------------------------------------------

# Cambodia's 25 provinces/municipalities (source: NIS / Wikipedia "Provinces
# of Cambodia", cross-checked July 2026). ASCII spelling, matching typical
# MOC spreadsheet exports. If your source uses accented forms (Kratié,
# Takéo) add them to PROVINCE_ALIASES below rather than changing this list,
# so the canonical value stays consistent.
CAMBODIA_PROVINCES = [
    "Banteay Meanchey", "Battambang", "Kampong Cham", "Kampong Chhnang",
    "Kampong Speu", "Kampong Thom", "Kampot", "Kandal", "Kep", "Koh Kong",
    "Kratie", "Mondulkiri", "Oddar Meanchey", "Pailin", "Phnom Penh",
    "Preah Sihanouk", "Preah Vihear", "Prey Veng", "Pursat", "Ratanakiri",
    "Siem Reap", "Stung Treng", "Svay Rieng", "Takeo", "Tboung Khmum",
]

# Common real-world spelling variants seen in MOC/OSH exports. Lowercased
# keys. Extend this as you encounter new variants in real data -- that's
# the point of keeping it separate from CAMBODIA_PROVINCES.
PROVINCE_ALIASES = {
    "sihanoukville": "Preah Sihanouk",
    "sihanouk": "Preah Sihanouk",
    "preah sihanoukville": "Preah Sihanouk",
    "kompong cham": "Kampong Cham",
    "kompong chhnang": "Kampong Chhnang",
    "kompong speu": "Kampong Speu",
    "kompong thom": "Kampong Thom",
    "kompong som": "Preah Sihanouk",
    "kratié": "Kratie",
    "kracheh": "Kratie",
    "takéo": "Takeo",
    "phnompenh": "Phnom Penh",
    "pp": "Phnom Penh",
    "otdar meanchey": "Oddar Meanchey",
    "tbong khmum": "Tboung Khmum",
    "steung treng": "Stung Treng",
    "svay rierng": "Svay Rieng",
}

# Approximate national bounding box (padded slightly beyond Cambodia's real
# ~10.4-14.7N / 102.3-107.6E extent). This is a coarse sanity check --
# enough to catch 0/0 placeholders, swapped lat/long, or stray digits --
# NOT a precise per-province boundary. Tighten with real GADM/OSM polygons
# per-province if you need that level of precision.
CAMBODIA_BBOX = {"lat": (9.0, 15.0), "long": (102.0, 108.0)}

# Khmer Unicode block.
KHMER_RANGE = re.compile(r"[\u1780-\u17FF]")

# Cambodian phone numbers: 0-prefixed local (8-9 digits after the 0) or
# +855 international form. Used as a schema `pattern` constraint too --
# kept here so it can be unit tested the same way as everything else.
PHONE_RE = re.compile(r"^(0\d{8,9}|\+855\d{8,9})$")

# Open Supply Hub OS ID: 15 characters = 2-letter country code + 4-digit
# year + 3-digit day-of-year + 6 alphanumeric characters. This is a
# *structural* check based on OS Hub's published ID scheme, not a live
# lookup, so it's treated as an advisory warning (see RULE_SEVERITY) rather
# than a hard rejection -- flag it for a human, don't silently drop a
# legitimate row over a regex mismatch.
OS_ID_RE = re.compile(r"^[A-Z]{2}\d{7}[A-Z0-9]{6}$")

EMPLOYEE_COUNT_WARN_THRESHOLD = 20000
DATE_MISMATCH_WARN_DAYS = 365


# ---------------------------------------------------------------------------
# Rule functions
# ---------------------------------------------------------------------------

def is_khmer_text(value: Optional[str]) -> bool:
    """True if value contains at least one Khmer-block character."""
    return bool(value) and bool(KHMER_RANGE.search(value))


def is_valid_phone(value: Optional[str]) -> bool:
    """True if value is blank (nullability is a separate, schema-level
    concern) or matches a Cambodian phone pattern."""
    if value in (None, ""):
        return True
    return bool(PHONE_RE.match(str(value).strip()))


def check_khmer_name(value: Optional[str]):
    if value in (None, ""):
        return None
    if is_khmer_text(value):
        return None
    return (
        "KM_NAME_NOT_KHMER",
        f'Factory Name (KM) "{value}" does not appear to contain Khmer '
        f"script -- check for a copy-paste or column-mapping error.",
    )


def check_geo_pair(lat: Union[str, float, None], lon: Union[str, float, None]):
    has_lat = lat not in (None, "")
    has_lon = lon not in (None, "")
    if has_lat != has_lon:
        return ("GEO_MISSING_PAIR", "Lat and Long must both be present or both be blank.")
    if not has_lat and not has_lon:
        return None
    try:
        lat_f, lon_f = float(lat), float(lon)
    except (TypeError, ValueError):
        return None  # a schema type-error will already flag this cell
    lat_lo, lat_hi = CAMBODIA_BBOX["lat"]
    lon_lo, lon_hi = CAMBODIA_BBOX["long"]
    if not (lat_lo <= lat_f <= lat_hi and lon_lo <= lon_f <= lon_hi):
        return (
            "GEO_OUT_OF_BOUNDS",
            f"({lat_f}, {lon_f}) falls outside Cambodia's bounding box "
            f"-- check for swapped lat/long or a mistyped digit.",
        )
    return None


def check_province(value: Optional[str]):
    if value in (None, ""):
        return None  # required-ness is a schema-level concern
    if value in CAMBODIA_PROVINCES:
        return None
    alias = PROVINCE_ALIASES.get(str(value).strip().lower())
    if alias:
        return (
            "PROVINCE_ALIAS",
            f'"{value}" looks like "{alias}" -- consider standardizing to the canonical name.',
        )
    close = get_close_matches(str(value), CAMBODIA_PROVINCES, n=1, cutoff=0.6)
    suggestion = f' Closest match: "{close[0]}".' if close else ""
    return ("PROVINCE_UNKNOWN", f'"{value}" is not one of Cambodia\'s 25 provinces.{suggestion}')


def check_dates(registered: Optional[datetime.date], registered_moc: Optional[datetime.date]):
    """`registered` / `registered_moc` are already-parsed datetime.date
    objects (or None) -- Frictionless casts `date`-typed schema fields
    before custom row checks run, so string parsing isn't needed here."""
    issues = []
    today = datetime.date.today()
    for value, field in ((registered, "Registered Date"), (registered_moc, "Registered Date (from MOC)")):
        if isinstance(value, datetime.date) and value > today:
            issues.append(("DATE_FUTURE", f"{field} ({value.isoformat()}) is in the future.", field))
    if isinstance(registered, datetime.date) and isinstance(registered_moc, datetime.date):
        delta = abs((registered - registered_moc).days)
        if delta > DATE_MISMATCH_WARN_DAYS:
            issues.append((
                "DATE_MISMATCH",
                f"Registered Date and Registered Date (from MOC) differ by {delta} days.",
                "Registered Date (from MOC)",
            ))
    return issues


def check_os_id(value: Optional[str]):
    if value in (None, ""):
        return None
    if OS_ID_RE.match(str(value).strip()):
        return None
    return (
        "OS_ID_FORMAT",
        f'"{value}" doesn\'t match the expected OS Hub ID shape (2-letter '
        f"country + 4-digit year + 3-digit day-of-year + 6 characters, 15 "
        f"total). Worth a second look, but not necessarily wrong.",
    )


def check_employee_count(value):
    try:
        n = int(value)
    except (TypeError, ValueError):
        return None
    if n > EMPLOYEE_COUNT_WARN_THRESHOLD:
        return ("EMPLOYEE_COUNT_OUTLIER", f"{n} employees is unusually high for a single factory -- worth a second look.")
    return None


# ---------------------------------------------------------------------------
# Self-tests. Run with: python -m gatekeeper.rules
# (No frictionless / pandas / network required -- stdlib only.)
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    passed = failed = 0

    def check(label, condition):
        global passed, failed
        if condition:
            passed += 1
        else:
            failed += 1
            print(f"FAIL: {label}")

    # Khmer script
    check("khmer text detected", is_khmer_text("រោងចក្រ​ភ្នំពេញ"))
    check("latin text rejected", not is_khmer_text("Phnom Penh Factory"))
    check("empty text rejected", not is_khmer_text(""))
    check("none text rejected", not is_khmer_text(None))

    # Phone
    check("local phone ok", is_valid_phone("012345678"))
    check("intl phone ok", is_valid_phone("+85512345678"))
    check("blank phone ok (nullability handled elsewhere)", is_valid_phone(""))
    check("garbage phone rejected", not is_valid_phone("call-me-maybe"))
    check("too-short phone rejected", not is_valid_phone("0123"))

    # Geo
    check("valid PP coords pass", check_geo_pair(11.5564, 104.9282) is None)
    check("blank pair passes", check_geo_pair("", "") is None)
    check("missing half fails", check_geo_pair(11.5564, "")[0] == "GEO_MISSING_PAIR")
    check("out of bounds fails", check_geo_pair(40.0, 104.9282)[0] == "GEO_OUT_OF_BOUNDS")
    check("swapped lat/long fails", check_geo_pair(104.9282, 11.5564)[0] == "GEO_OUT_OF_BOUNDS")

    # Province
    check("exact province passes", check_province("Phnom Penh") is None)
    check("blank province passes (required handled by schema)", check_province("") is None)
    check("alias resolved", check_province("Sihanoukville")[0] == "PROVINCE_ALIAS")
    check("typo flagged unknown", check_province("Phnom Pehn")[0] == "PROVINCE_UNKNOWN")
    check("nonsense flagged unknown", check_province("Atlantis")[0] == "PROVINCE_UNKNOWN")
    check("all 25 provinces are self-consistent", all(check_province(p) is None for p in CAMBODIA_PROVINCES))
    check("province list has 25 entries", len(CAMBODIA_PROVINCES) == 25)

    # Dates
    today = datetime.date.today()
    yesterday = today - datetime.timedelta(days=1)
    future = today + datetime.timedelta(days=10)
    long_ago = today - datetime.timedelta(days=3000)
    check("two consistent past dates -> no issues", check_dates(yesterday, yesterday) == [])
    check("future date flagged", any(c == "DATE_FUTURE" for c, *_ in check_dates(future, yesterday)))
    check("mismatched dates flagged", any(c == "DATE_MISMATCH" for c, *_ in check_dates(yesterday, long_ago)))
    check("missing dates -> no crash, no issues", check_dates(None, None) == [])

    # OS ID
    check("well-formed OS ID passes", check_os_id("KH2019278AB12CD") is None)
    check("blank OS ID passes", check_os_id("") is None)
    check("malformed OS ID flagged", check_os_id("not-an-os-id")[0] == "OS_ID_FORMAT")

    # Employee count
    check("normal headcount passes", check_employee_count(3000) is None)
    check("huge headcount flagged", check_employee_count(50000)[0] == "EMPLOYEE_COUNT_OUTLIER")
    check("non-numeric headcount doesn't crash", check_employee_count("many") is None)

    print(f"\n{passed} passed, {failed} failed")
    raise SystemExit(1 if failed else 0)
