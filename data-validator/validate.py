#!/usr/bin/env python3
"""
Gatekeeper CLI
==============
Validates an incoming factory-registry CSV/JSON file against
schema/factory_schema.json (a Frictionless Table Schema) plus the custom
cross-field rules in gatekeeper/checks.py, before the file is allowed
downstream (published, merged, analyzed, etc).

Usage:
    python validate.py data.csv
    python validate.py data.json --schema schema/factory_schema.json
    python validate.py data.csv --log report.json --strict

Exit codes (useful for CI / pipeline gating):
    0  data passed (no blocking errors; warnings are still printed)
    1  data failed (at least one blocking error, or --strict + warnings)
    2  the tool itself couldn't run (bad args, frictionless not installed, etc)
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

import click

from gatekeeper.messages import enrich_issue, humanize_schema_issue

DEFAULT_SCHEMA = Path(__file__).parent / "schema" / "factory_schema.json"

# Matches the "[RULE_CODE] message" convention that gatekeeper/checks.py
# writes into each custom error's `note`. Errors that don't match this
# (i.e. everything Frictionless raises natively from the schema itself --
# type-error, required-error, pattern-constraint, unique-error, ...) fall
# through to the default "error" severity.
_NOTE_CODE_RE = re.compile(r"^\[([A-Z_]+)\]\s*(.*)$", re.DOTALL)

_SCHEMA_ERROR_TYPES = {
    "constraint-error",
    "type-error",
    "unique-error",
    "required-error",
    "extra-label",
    "missing-label",
    "blank-header",
    "duplicate-label",
}


def _parse_note(note, message):
    """Returns (rule_code_or_None, display_message).

    For custom-rule issues, `note` carries our own "[CODE] message" and we
    show that message directly. For native Frictionless schema errors,
    `note` is often a terse fragment (e.g. 'type is "integer/default"') --
    `message` is the fuller, human-readable version, so we prefer that.
    """
    note = note or ""
    m = _NOTE_CODE_RE.match(note)
    if m:
        return m.group(1), m.group(2)
    return None, (message or note or "(no message)")


def _load_checks():
    from gatekeeper.checks import build_checks
    return build_checks()


def _resource_from_path(data_path: str, schema):
    """Build a Frictionless Resource for CSV or flat JSON.

    JSON files are loaded as inline row data. Passing a .json path alone
    makes Frictionless treat it as a JSON *document* (not a table), and
    the streaming JSON table parser also needs the optional
    ``frictionless[json]`` extra -- neither of which we want for this CLI.
    """
    from frictionless import Resource

    path = Path(data_path)
    if path.suffix.lower() == ".json":
        payload = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(payload, list):
            raise ValueError(
                "JSON input must be a flat array of row objects, "
                'e.g. [{"Factory Name (EN)": "...", ...}, ...]'
            )
        return Resource(data=payload, schema=schema)
    return Resource(path=data_path, schema=schema)


def _run_validation(data_path: str, schema_path: str):
    from frictionless import Schema, system
    from frictionless import validate as frictionless_validate

    # Frictionless treats absolute paths as unsafe by default (path-traversal
    # guard). This CLI intentionally opens user-supplied local files, so we
    # mark the run as trusted -- same as `frictionless validate --trusted`.
    with system.use_context(trusted=True):
        schema = Schema.from_descriptor(schema_path)
        resource = _resource_from_path(data_path, schema)
        return frictionless_validate(resource, type="resource", checks=_load_checks())


def _issues_from_report(report, rule_severity: dict):
    flat = report.flatten(["rowNumber", "fieldName", "type", "note", "message"])
    issues = []
    for row_number, field_name, err_type, note, message in flat:
        rule_code, display_message = _parse_note(note, message)

        if rule_code:
            code = rule_code
            title = None
            fix = None
            severity = rule_severity.get(rule_code, "error")
        elif err_type in _SCHEMA_ERROR_TYPES or err_type == "constraint-error":
            code, title, display_message, fix = humanize_schema_issue(
                err_type, field_name, note or "", message or "",
            )
            severity = "error"
        else:
            code = err_type
            title = None
            fix = None
            severity = "error"

        issue = {
            "row": row_number,
            "field": field_name,
            "type": code,
            "severity": severity,
            "message": display_message,
        }
        if title:
            issue["title"] = title
        if fix:
            issue["fix"] = fix
        issues.append(enrich_issue(issue))
    return issues


def _where(item) -> str:
    """Short 'Row N · Field' location label."""
    parts = []
    if item.get("row") is not None:
        parts.append(f"Row {item['row']}")
    else:
        parts.append("File")
    if item.get("field"):
        parts.append(item["field"])
    return " · ".join(parts)


def _print_issue(index: int, item: dict, color: str):
    loc = _where(item)
    title = item.get("title") or item["type"]
    click.echo()
    click.secho(f"  {index}. {loc}", fg=color, bold=True, nl=False)
    click.echo(f"  [{item['type']}]")
    click.secho(f"     {title}", bold=True)
    if item.get("explain") or item.get("message"):
        click.echo(f"     {item.get('explain') or item['message']}")
    if item.get("fix"):
        click.secho("     Fix: ", fg="cyan", nl=False)
        click.echo(item["fix"])


def _print_group(label: str, blurb: str, items: list, color: str, max_print: int):
    if not items:
        return
    click.echo()
    click.secho("─" * 64, fg=color)
    click.secho(f"{label} ({len(items)})", fg=color, bold=True)
    click.secho("─" * 64, fg=color)
    click.echo(blurb)
    for i, item in enumerate(items[:max_print], start=1):
        _print_issue(i, item, color)
    if len(items) > max_print:
        leftover = len(items) - max_print
        click.echo()
        click.echo(f"  … and {leftover} more (see the JSON log for the full list)")


def _print_summary(data_path, errors_, warnings_, max_print, strict, log_path):
    click.echo()
    click.secho("Factory Registry Gatekeeper", bold=True)
    click.echo(f"File: {data_path}")
    click.echo("─" * 64)

    if not errors_ and not warnings_:
        click.secho("PASSED", fg="green", bold=True, nl=False)
        click.echo(" — no issues found. This file is clear to publish.")
        return

    if errors_:
        click.secho("FAILED", fg="red", bold=True, nl=False)
        click.echo(
            f" — {len(errors_)} error(s) must be fixed before this file can pass."
        )
        if warnings_:
            click.echo(
                f"       Also found {len(warnings_)} warning(s) worth reviewing "
                "(warnings do not block unless you use --strict)."
            )
    else:
        click.secho("PASSED WITH WARNINGS", fg="yellow", bold=True, nl=False)
        click.echo(f" — {len(warnings_)} warning(s) found.")
        if strict:
            click.echo("       (--strict is on, so warnings also fail the gate.)")
        else:
            click.echo(
                "       The file can still pass; review the warnings below "
                "when you can."
            )

    _print_group(
        "ERRORS — blocking",
        "These stop the file from passing. Correct each one, then re-run.",
        errors_,
        "red",
        max_print,
    )
    _print_group(
        "WARNINGS — advisory",
        "These look unusual or inconsistent. Worth a human check, but they "
        "do not block by default.",
        warnings_,
        "yellow",
        max_print,
    )

    click.echo()
    click.echo("─" * 64)
    click.echo(
        f"Summary: {len(errors_)} error(s) · {len(warnings_)} warning(s)"
    )
    if log_path:
        click.echo(f"Full report: {log_path}")
    if errors_ or (strict and warnings_):
        click.echo()
        click.secho("Next steps", bold=True)
        click.echo("  1. Fix the issues listed above in your spreadsheet/CSV.")
        click.echo(f"  2. Re-run:  python validate.py {data_path}")
        if warnings_ and not strict:
            click.echo("  Tip: use --strict if you also want warnings to fail the gate.")


@click.command(
    context_settings={"help_option_names": ["-h", "--help"]},
    epilog=(
        "\b\n"
        "Exit codes:\n"
        "  0  passed (no blocking errors)\n"
        "  1  failed (blocking errors, or warnings with --strict)\n"
        "  2  tool error (bad args, missing dependency, …)\n"
        "\n"
        "Examples:\n"
        "  python validate.py sample_data/invalid_sample.csv\n"
        "  python validate.py data.csv --strict --log report.json\n"
        "  python validate.py data.csv --quiet\n"
    ),
)
@click.argument("data_path", type=click.Path(exists=True, dir_okay=False))
@click.option(
    "--schema", "schema_path",
    type=click.Path(exists=True, dir_okay=False),
    default=str(DEFAULT_SCHEMA), show_default=True,
    help="Table Schema JSON that defines column types and constraints.",
)
@click.option(
    "--log", "log_path",
    type=click.Path(dir_okay=False), default="validation_report.json", show_default=True,
    help="Where to write the full structured issue report (JSON).",
)
@click.option("--no-log", is_flag=True, help="Skip writing the JSON report file.")
@click.option(
    "--strict", is_flag=True,
    help="Also fail the gate on warnings (not just errors).",
)
@click.option(
    "--max-print", default=25, show_default=True,
    help="Max issues to print per section in the console.",
)
@click.option(
    "--quiet", is_flag=True,
    help="Only print the final PASS/FAIL line (for scripts/CI).",
)
def main(data_path, schema_path, log_path, no_log, strict, max_print, quiet):
    """Validate a factory-registry DATA_PATH (CSV or JSON) before publishing.

    Checks every row against the schema (types, required fields, patterns,
    uniqueness) plus Cambodia-specific rules (provinces, coordinates,
    Khmer names, date consistency, and more).

    \b
    Output is split into two groups:
      ERRORS    Blocking — must be fixed for the file to pass
      WARNINGS  Advisory — worth review; do not block unless --strict

    DATA_PATH may be a .csv file, or a .json file containing a flat array
    of row objects.
    """
    try:
        report = _run_validation(data_path, schema_path)
    except ImportError:
        click.echo(
            "frictionless isn't installed in this environment.\n"
            "Run:  pip install -r requirements.txt",
            err=True,
        )
        sys.exit(2)
    except Exception as exc:  # surface anything unexpected instead of a raw traceback
        click.echo(f"Could not run validation: {exc}", err=True)
        sys.exit(2)

    from gatekeeper.rules import RULE_SEVERITY

    issues = _issues_from_report(report, RULE_SEVERITY)
    errors_ = [i for i in issues if i["severity"] == "error"]
    warnings_ = [i for i in issues if i["severity"] == "warning"]
    gate_failed = bool(errors_) or (strict and bool(warnings_))
    out_log = None if no_log else log_path

    if quiet:
        click.secho(
            "FAIL" if gate_failed else "PASS",
            fg="red" if gate_failed else "green",
            bold=True,
        )
    else:
        _print_summary(data_path, errors_, warnings_, max_print, strict, out_log)

    if not no_log:
        Path(log_path).write_text(json.dumps({
            "source": str(data_path),
            "schema": str(schema_path),
            "valid": not gate_failed,
            "strict_mode": strict,
            "error_count": len(errors_),
            "warning_count": len(warnings_),
            "issues": issues,
        }, indent=2, default=str))
        if quiet:
            # Quiet mode still writes the log; mention it on stderr so
            # stdout stays a clean PASS/FAIL line for scripts.
            click.echo(f"Full report written to {log_path}", err=True)

    sys.exit(1 if gate_failed else 0)


if __name__ == "__main__":
    main()
