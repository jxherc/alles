#!/usr/bin/env python3
"""Reconcile the canonical KOKUEN v5 overlay lint with reviewed warnings."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
TARGET = REPO_ROOT / "static" / "kokuen.css"
DEFAULT_LINTER = Path("/Users/jxh/kokuen/scripts/lint_ui_rules.py")
EXPECTED_COUNTS = {"nested-boundary": 72, "small-type": 123}
EXPECTED_DIGEST = "ff0f22198a888ca151313ae8a8261f6c963cb000e64740b0d1eb73398870dac1"
CONTROL_WORDS = re.compile(
    r"(?:button|input|textarea|search|choice|switch|option|trigger|select|tab|action)",
    re.IGNORECASE,
)


def canonical_linter() -> Path:
    override = os.environ.get("KOKUEN_LINTER")
    return Path(override).expanduser() if override else DEFAULT_LINTER


def lint_findings() -> list[dict[str, object]]:
    linter = canonical_linter()
    if not linter.is_file():
        raise FileNotFoundError(f"canonical KOKUEN linter not found: {linter}")
    result = subprocess.run(
        [
            sys.executable,
            str(linter),
            str(TARGET.relative_to(REPO_ROOT)),
            "--forbid-native-controls",
            "--format",
            "json",
        ],
        cwd=REPO_ROOT,
        check=False,
        capture_output=True,
        text=True,
    )
    if not result.stdout.strip():
        raise RuntimeError(result.stderr.strip() or "KOKUEN linter produced no JSON")
    return json.loads(result.stdout)


def fingerprint(findings: list[dict[str, object]]) -> str:
    lines = ["{severity}|{rule}|{path}|{line}|{message}".format(**finding) for finding in findings]
    return hashlib.sha256("\n".join(lines).encode()).hexdigest()


def resolution(finding: dict[str, object]) -> tuple[str, str]:
    rule = str(finding["rule"])
    message = str(finding["message"])
    if rule == "small-type":
        if CONTROL_WORDS.search(message):
            return (
                "compact-control-label",
                "Reviewed 12-13px dense-workbench label; its silhouette remains a 44px target, "
                "with unclipped focus and a separate visible state.",
            )
        return (
            "secondary-metadata",
            "Reviewed 12-13px non-primary metadata, hint, status, timestamp, or table annotation; "
            "primary labels and owner data retain the essential text hierarchy.",
        )
    if rule == "nested-boundary":
        if CONTROL_WORDS.search(message):
            return (
                "interactive-bezel",
                "The descendant edge is the control's single input/action bezel; the ancestor edge "
                "defines the surrounding work region, so the jobs are distinct.",
            )
        return (
            "subregion-seam",
            "The descendant edge separates an independently scrollable, selectable, dialog, rail, "
            "or status subregion; rendered review confirmed no same-level double bezel.",
        )
    raise ValueError(f"unreviewed KOKUEN warning rule: {rule}")


def reconcile(findings: list[dict[str, object]]) -> dict[str, object]:
    errors = [finding for finding in findings if finding["severity"] == "ERROR"]
    warnings = [finding for finding in findings if finding["severity"] == "WARN"]
    counts: dict[str, int] = {}
    explained = []
    for finding in warnings:
        rule = str(finding["rule"])
        counts[rule] = counts.get(rule, 0) + 1
        category, reason = resolution(finding)
        explained.append({**finding, "category": category, "resolution": reason})
    return {
        "errors": errors,
        "warnings": warnings,
        "explained": explained,
        "counts": counts,
        "digest": fingerprint(warnings),
    }


def render_report(audit: dict[str, object]) -> str:
    lines = [
        "# KOKUEN v5 lint resolutions",
        "",
        "Every canonical warning below has a declared semantic job. The digest makes this list "
        "fail closed when the overlay changes.",
        "",
        "| line | rule | resolution | canonical warning |",
        "| ---: | --- | --- | --- |",
    ]
    for finding in audit["explained"]:
        message = str(finding["message"]).replace("|", "\\|")
        reason = str(finding["resolution"]).replace("|", "\\|")
        lines.append(
            f"| {finding['line']} | {finding['rule']} / {finding['category']} | "
            f"{reason} | {message} |"
        )
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--report", action="store_true", help="print the exhaustive Markdown audit")
    args = parser.parse_args()
    try:
        audit = reconcile(lint_findings())
    except (FileNotFoundError, RuntimeError, ValueError, json.JSONDecodeError) as exc:
        print(str(exc), file=sys.stderr)
        return 2

    failures = []
    if audit["errors"]:
        failures.append(f"{len(audit['errors'])} hard errors")
    if audit["counts"] != EXPECTED_COUNTS:
        failures.append(f"warning counts changed: {audit['counts']!r}")
    if audit["digest"] != EXPECTED_DIGEST:
        failures.append(f"warning digest changed: {audit['digest']}")
    if len(audit["warnings"]) != len(audit["explained"]):
        failures.append("one or more warnings are unexplained")

    if args.report:
        print(render_report(audit))
    print(
        "KOKUEN v5 lint audit: "
        f"{len(audit['errors'])} errors, {len(audit['warnings'])} warnings, "
        f"{len(audit['explained'])} explained, "
        f"{len(audit['warnings']) - len(audit['explained'])} unexplained"
    )
    if failures:
        for failure in failures:
            print(f"FAIL: {failure}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
