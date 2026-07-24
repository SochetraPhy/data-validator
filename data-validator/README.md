# Factory Registry Gatekeeper

A lightweight validation "gatekeeper" for the Cambodia factory-registry
dataset (MOC / Open Supply Hub style exports). It checks an incoming
CSV or JSON file against a schema before the file gets published,
merged, or analyzed, and produces a clear pass/fail report plus a
structured error log.

Built on [Frictionless Framework](https://framework.frictionlessdata.io/)
for schema-level validation (types, required/unique fields, patterns,
formats), with a small custom-rules layer for the cross-field checks a
schema can't express on its own (province validity, geo bounding box,
date consistency, Khmer script, OS Hub ID shape, employee-count
outliers).

## 1. Install

Needs **Python 3.10+** (tested on 3.13). From a terminal:

```bash
cd /path/to/data-validator          # must be the project root
python3 -m venv .venv
source .venv/bin/activate           # Windows: .venv\Scripts\activate
pip install -r requirements.txt
```

Keep the venv activated for every command below (`(.venv)` should appear in
your prompt). If `pip` refuses with an "externally-managed-environment"
error, you skipped the venv — create/activate it and retry.

## 2. Run it

```bash
python validate.py sample_data/invalid_sample.csv
```

```
Factory Registry Gatekeeper
File: sample_data/invalid_sample.csv
────────────────────────────────────────────────────────────────
FAILED — 10 error(s) must be fixed before this file can pass.
       Also found 5 warning(s) worth reviewing (warnings do not block unless you use --strict).

────────────────────────────────────────────────────────────────
ERRORS — blocking (10)
────────────────────────────────────────────────────────────────
These stop the file from passing. Correct each one, then re-run.

  1. Row 3 · Factory Name (EN)  [required-error]
     Required field missing
     "Factory Name (EN)" is required but this cell is empty.
     Fix: Enter a value for "Factory Name (EN)".

  2. Row 4 · Owner Phone  [pattern-error]
     Value doesn't match the expected pattern
     "call-me-maybe" in "Owner Phone" is not in the accepted format.
     Fix: Use a Cambodian number: 0XXXXXXXX / 0XXXXXXXXX, or +855XXXXXXXX / +855XXXXXXXXX.

  ...

────────────────────────────────────────────────────────────────
WARNINGS — advisory (5)
────────────────────────────────────────────────────────────────
  1. Row 5 · Factory Name (KM)  [KM_NAME_NOT_KHMER]
     ...
  2. Row 6 · Province  [PROVINCE_ALIAS]
     "Sihanoukville" looks like "Preah Sihanouk" ...

────────────────────────────────────────────────────────────────
Summary: 10 error(s) · 5 warning(s)
Full report: validation_report.json
```

Exit codes (so it can gate a CI step or pipeline):

| Code | Meaning |
|---|---|
| `0` | Passed -- no blocking errors |
| `1` | Failed -- at least one blocking error (or a warning, with `--strict`) |
| `2` | The tool itself couldn't run (bad args, dependency missing, etc.) |

Try the clean fixtures too:

```bash
python validate.py sample_data/valid_sample.csv
python validate.py sample_data/sample.json
```

Or the other failing fixtures:

```bash
python validate.py sample_data/invalid_sample.json
python validate.py sample_data/dirty_sample.json
```

### Options

```
python validate.py DATA_PATH [OPTIONS]

  --schema FILE         Table Schema JSON to validate against  [default: schema/factory_schema.json]
  --log FILE            Where to write the full JSON issue report [default: validation_report.json]
  --no-log              Skip writing the JSON report file
  --strict              Also fail the gate on warnings, not just errors
  --max-print INTEGER   Max issues printed per section in the console  [default: 25]
  --quiet               Print only the final PASS/FAIL line (for scripting)
```

`DATA_PATH` can be a `.csv` file, or a `.json` file containing a flat
array of row objects, e.g.:

```json
[
  {"Factory Name (EN)": "Example Co.", "Province": "Kandal", "...": "..."},
  {"Factory Name (EN)": "Another Co.", "Province": "Kampot", "...": "..."}
]
```

Nested JSON isn't supported out of the box -- flatten it first (or ask
for help extending `validate.py` to do so).

After each run (unless you pass `--no-log`), results are also written to
`validation_report.json`: source path, pass/fail, counts, and the full
`issues` list for scripts/CI/review.

## 3. How validation is split across layers

This is the main thing to understand if you're going to extend the
tool. Each concern lives in exactly one place:

| Layer | File | Owns |
|---|---|---|
| **Schema** | `schema/factory_schema.json` | Per-column type, required/unique, regex `pattern`, `format` (email/uri). Anything Frictionless can check about *one cell in isolation*. |
| **Rules** | `gatekeeper/rules.py` | Plain-Python functions for anything that needs *more than one field*, a reference list, or fuzzy matching (province validity, lat/long pairing + bounding box, date-vs-date, OS ID shape, employee-count outliers, Khmer-script check). Zero Frictionless dependency -- fully unit-testable on its own. |
| **Checks** | `gatekeeper/checks.py` | Thin Frictionless `Check` plugin classes that call the `rules.py` functions and turn their results into validation errors Frictionless can report alongside the schema errors. |
| **Messages** | `gatekeeper/messages.py` | Plain-language titles, explanations, and fix tips for both custom rule codes and native schema errors. Used by the console report; the JSON log still keeps `type` / `message`. |

`validate.py` ties them together: it loads the schema, registers the
custom checks, runs `frictionless.validate(...)`, humanizes each issue,
and classifies it as **error** (blocks the gate) or **warning**
(shown for review but doesn't block) using `gatekeeper/rules.py:RULE_SEVERITY`.
Native schema violations (missing required field, bad type, duplicate
ID, pattern mismatch) are always errors. Custom-rule issues are error
or warning depending on how confident the rule is -- e.g. an unknown
province is an error, but a recognized misspelling like "Sihanoukville"
is a warning because we already know what it should be.

## 4. Design decisions worth knowing about

- **Province is a custom check, not a schema `enum`.** A hard enum
  would just reject anything that isn't an exact string match. The
  custom check instead recognizes common variant spellings (see
  `PROVINCE_ALIASES` in `rules.py`) and suggests the closest match for
  genuine typos, which is more useful for messy field-collected data.
- **Several categorical columns (`Region`, `Sector`, `Source`, `Result
  (Betterwork)`, `Search Result (in MOC)`) are left as free text**
  rather than a schema `enum`, on purpose -- guessing the wrong
  controlled vocabulary would cause false rejections of real data. Once
  you've confirmed the exact category labels your source system uses,
  add an `"enum": [...]` to that field's `constraints` in
  `schema/factory_schema.json`.
- **`ID in MOC` has no pattern constraint** -- there wasn't a
  confidently-known MOC registration-number format available while
  building this. Add one once you've confirmed it against real data.
- **The OS Hub ID check is advisory (a warning), not a hard error.**
  It checks the published structural shape (2-letter country code +
  4-digit year + 3-digit day-of-year + 6 characters = 15 total) but
  isn't a live lookup against Open Supply Hub, so a mismatch is
  flagged for a human rather than silently rejecting the row.
- **`Province` -> `District` -> `Commune` hierarchy is *not* cross-checked.**
  Doing that properly needs a real gazetteer (all 25 provinces x ~200
  districts x ~1,600 communes) which wasn't safe to hand-write from
  memory into a "reference dataset" that looks authoritative but might
  quietly be wrong or incomplete. See "Extending this tool" below.
- **The Lat/Long check is a coarse national bounding box**, not a
  per-province polygon -- enough to catch swapped coordinates, `0,0`
  placeholders, or a stray extra digit, not to confirm a point sits
  inside the correct province.

## 5. Extending this tool

- **Province/District/Commune hierarchy:** download a gazetteer (e.g.
  from NIS Cambodia, GADM, or OpenStreetMap/HDX) as a CSV of
  `province,district,commune`, load it in `gatekeeper/rules.py`, and
  add a `check_location_hierarchy(province, district, commune)`
  function + a matching `Check` class in `checks.py`, following the
  same pattern as `ProvinceCheck`.
- **Tighter per-province bounding boxes:** replace the single
  `CAMBODIA_BBOX` in `rules.py` with a `dict` keyed by province, sourced
  from real GIS boundary data.
- **Auto-splitting valid/invalid rows:** `report.flatten([...])`
  includes a `rowNumber` for each issue (1-indexed, with the header as
  row 1, so a CSV's first data row is `rowNumber == 2`). A natural next
  step is to use that to write `clean_rows.csv` /
  `needs_review_rows.csv` alongside `validation_report.json`, so staff
  only have to look at what actually failed. This wasn't included in
  v1 so it could be tested properly first -- happy to add it.
- **New rules in general:** add a pure function to `rules.py` (and a
  test in its `__main__` block), wrap it in a `Check` class in
  `checks.py`, add it to `ALL_CHECKS`, give it a severity in
  `RULE_SEVERITY` (omit it if it should always be a hard error), and
  add a short guide entry in `gatekeeper/messages.py` so the console
  shows a clear title/fix tip.

## 6. Testing

### Business-logic unit checks (no Frictionless required)

```bash
python -m gatekeeper.rules
```

This runs 31 self-checks covering every rule (Khmer script, phone
format, geo pairing/bounds, province matching/aliasing, date
consistency, OS ID shape, employee-count outliers) and exits non-zero
if anything fails -- safe to wire into CI as a fast pre-check.

### End-to-end against sample fixtures

```bash
# Should PASS
python validate.py sample_data/valid_sample.csv
python validate.py sample_data/sample.json

# Should FAIL (blocking errors)
python validate.py sample_data/invalid_sample.csv
python validate.py sample_data/invalid_sample.json
python validate.py sample_data/dirty_sample.json

# Script-friendly
python validate.py sample_data/invalid_sample.csv --quiet
```

Exit code `0` = pass, `1` = fail. Open `validation_report.json` (or pass
`--log path.json`) for the full structured issue list.
