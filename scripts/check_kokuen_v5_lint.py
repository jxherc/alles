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
REGISTRY = REPO_ROOT / "scripts" / "kokuen_v5_lint_registry.json"
TARGET_PATH = TARGET.relative_to(REPO_ROOT).as_posix()
# Match the canonical linter's CSS_RULE and match.start() line anchor, including
# leading whitespace/comments in the hashed block.
CSS_RULE = re.compile(r"(?P<selectors>[^{}]+)\{(?P<body>[^{}]*)\}", re.DOTALL)
REGISTRY_FIELDS = {"rule", "message", "css_block_sha256", "path", "selector", "job", "reason"}


def canonical_linter() -> Path:
    override = os.environ.get("KOKUEN_LINTER")
    if override:
        return Path(override).expanduser()
    candidates = (
        REPO_ROOT.parent / "kokuen" / "scripts" / "lint_ui_rules.py",
        Path.home() / ".agents" / "skills" / "kokuen" / "scripts" / "lint_ui_rules.py",
        Path.home() / ".codex" / "skills" / "kokuen" / "scripts" / "lint_ui_rules.py",
        Path.home() / "kokuen" / "scripts" / "lint_ui_rules.py",
    )
    return next((path for path in candidates if path.is_file()), candidates[0])


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
    findings = json.loads(result.stdout)
    has_errors = isinstance(findings, list) and any(
        isinstance(finding, dict) and finding.get("severity") == "ERROR" for finding in findings
    )
    if result.returncode not in (0, 1) or (result.returncode == 1 and not has_errors):
        raise RuntimeError(f"canonical KOKUEN linter failed (exit {result.returncode})")
    return findings


def warning_key(finding: dict[str, object]) -> tuple[str, str, str]:
    return finding["rule"], finding["message"], finding["css_block_sha256"]


def reconcile(
    findings: list[dict[str, object]], registry: list[dict[str, str]], css_text: str
) -> dict[str, object]:
    if not isinstance(findings, list):
        raise ValueError("canonical findings must be a list")
    for finding in findings:
        if (
            not isinstance(finding, dict)
            or finding.get("severity") not in ("ERROR", "WARN")
            or any(
                not isinstance(finding.get(field), str) or not finding[field].strip()
                for field in ("rule", "path", "message")
            )
            or type(finding.get("line")) is not int
            or finding["line"] < 1
        ):
            raise ValueError(f"invalid canonical finding: {finding!r}")
    if not isinstance(registry, list):
        raise ValueError("warning registry must be a list")
    approved = {}
    for entry in registry:
        if (
            not isinstance(entry, dict)
            or set(entry) != REGISTRY_FIELDS
            or any(not isinstance(value, str) or not value.strip() for value in entry.values())
            or entry["path"] != TARGET_PATH
            or not re.fullmatch(r"[0-9a-f]{64}", entry["css_block_sha256"])
        ):
            raise ValueError(f"invalid warning registry entry: {entry!r}")
        key = warning_key(entry)
        if key in approved:
            raise ValueError(f"duplicate warning registry entry: {key!r}")
        approved[key] = entry

    blocks = {}
    for match in CSS_RULE.finditer(css_text):
        line = css_text.count("\n", 0, match.start()) + 1
        selector = re.sub(r"/\*.*?\*/", "", match.group("selectors"), flags=re.DOTALL).strip()
        blocks.setdefault(line, []).append(
            {
                "selector": " ".join(selector.split()),
                "css_block_sha256": hashlib.sha256(match.group(0).encode("utf-8")).hexdigest(),
            }
        )
    errors = [finding for finding in findings if finding["severity"] == "ERROR"]
    warnings = [finding for finding in findings if finding["severity"] == "WARN"]
    explained = []
    unexplained = []
    matched = set()
    seen = set()
    for finding in warnings:
        candidates = blocks.get(finding["line"], [])
        if finding["path"] != TARGET_PATH or len(candidates) != 1:
            unexplained.append({**finding, "reason": "missing or ambiguous canonical source block"})
            continue
        anchored = {**finding, **candidates[0]}
        key = warning_key(anchored)
        if key in seen:
            raise ValueError(f"duplicate canonical warning identity: {key!r}")
        seen.add(key)
        entry = approved.get(key)
        if entry is None:
            unexplained.append({**anchored, "reason": "no exact reviewed registry entry"})
        elif entry["path"] != finding["path"] or entry["selector"] != anchored["selector"]:
            unexplained.append({**anchored, "reason": "registered path or selector does not match"})
        else:
            matched.add(key)
            explained.append({**anchored, "job": entry["job"], "reason": entry["reason"]})
    stale = [entry for key, entry in approved.items() if key not in matched]
    failures = []
    if errors:
        failures.append(f"{len(errors)} hard errors")
    if unexplained:
        failures.append(f"{len(unexplained)} warnings have no exact reviewed resolution")
    if stale:
        failures.append(f"{len(stale)} stale registry entries have no matching warning")
    return {
        "errors": errors,
        "warnings": warnings,
        "explained": explained,
        "unexplained": unexplained,
        "stale": stale,
        "failures": failures,
    }


def render_report(audit: dict[str, object]) -> str:
    lines = [
        "# KOKUEN v5 lint resolutions",
        "",
        "Only exact rule, message, source block, path, and selector matches use a registered "
        "semantic job. Pending warnings, stale entries, and canonical errors fail the gate.",
        "",
        "| status | source | rule | selector | block SHA-256 | job / reason | canonical warning |",
        "| --- | --- | --- | --- | --- | --- | --- |",
    ]
    for status, group in (
        ("registered", "explained"),
        ("PENDING", "unexplained"),
        ("STALE", "stale"),
        ("ERROR", "errors"),
    ):
        for finding in audit[group]:
            cells = [
                status,
                f"{finding['path']}:{finding.get('line', '-')}",
                finding["rule"],
                finding.get("selector", "-"),
                finding.get("css_block_sha256", "-"),
                f"{finding.get('job', '-')} / {finding.get('reason', '-')}",
                finding["message"],
            ]
            cells = [str(cell).replace("|", "\\|").replace("\n", " ") for cell in cells]
            lines.append("| " + " | ".join(cells) + " |")
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--report", action="store_true", help="print the exhaustive Markdown audit")
    args = parser.parse_args()
    try:
        registry = json.loads(REGISTRY.read_text(encoding="utf-8"))
        css_text = TARGET.read_text(encoding="utf-8")
        findings = lint_findings()
        if TARGET.read_text(encoding="utf-8") != css_text:
            raise RuntimeError("CSS changed while the canonical linter was running")
        audit = reconcile(findings, registry, css_text)
    except (OSError, RuntimeError, ValueError) as exc:
        print(str(exc), file=sys.stderr)
        return 2

    if args.report:
        print(render_report(audit))
    print(
        "KOKUEN v5 lint audit: "
        f"{len(audit['errors'])} errors, {len(audit['warnings'])} warnings, "
        f"{len(audit['explained'])} explained, "
        f"{len(audit['unexplained'])} unexplained, {len(audit['stale'])} stale"
    )
    if audit["failures"]:
        for failure in audit["failures"]:
            print(f"FAIL: {failure}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
