#!/usr/bin/env python3
"""Render the authoritative feature catalog and acceptance matrix."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from services.feature_registry import REGISTRY_PATH, feature_rows, load_registry  # noqa: E402


CATALOG_PATH = ROOT / "docs" / "feature-catalog.md"
MATRIX_PATH = ROOT / "docs" / "feature-acceptance-matrix.md"


def _display(value: str) -> str:
    return value.replace("-", " ").replace("_", " ")


def _list(values: list[str]) -> str:
    return ", ".join(f"`{value}`" for value in values) if values else "none"


def render_catalog(document: dict) -> str:
    lines = [
        "# Alles feature catalog",
        "",
        "Generated from `features/registry.json`. Edit the registry, then run",
        "`python scripts/generate_feature_catalog.py`. Do not hand-edit this file.",
        "",
    ]
    current = None
    for feature in feature_rows(document):
        if feature["category"] != current:
            current = feature["category"]
            lines.extend((f"## {_display(current).title()}", ""))
        coverage = feature["coverage"]
        lines.extend(
            (
                f"### {feature['id']}",
                "",
                feature["behavior"],
                "",
                f"- app: `{feature['app']}`",
                f"- risk: `{feature['risk']}`",
                f"- implementation: `{feature['implementation']}`",
                f"- acceptance: `{feature['acceptance']}`",
                f"- acceptance evidence: {feature.get('notes', 'not recorded')}",
                f"- platforms: {_list(feature['platforms'])}",
                f"- dependencies: {_list(feature['dependencies'])}",
                f"- Aide tools: {_list(feature['aide_tools'])}",
                f"- automated tests: {_list(feature['automated_tests'])}",
                f"- real-computer scenarios: {_list(feature['computer_scenarios'])}",
                f"- route owners: {_list(coverage['route_modules'])}",
                f"- control roots: {_list(coverage['control_roots'])}",
                f"- CLI commands: {_list(coverage['cli_commands'])}",
                f"- jobs: {_list(coverage['jobs'])}",
                f"- automation actions: {_list(coverage['automation_actions'])}",
                f"- integrations: {_list(coverage['integrations'])}",
                f"- PWA functions: {_list(coverage['pwa_functions'])}",
                f"- extension functions: {_list(coverage['extension_functions'])}",
                "",
            )
        )
    return "\n".join(lines).rstrip() + "\n"


def render_matrix(document: dict) -> str:
    lines = [
        "# Alles feature acceptance matrix",
        "",
        "Generated from `features/registry.json`. `unchecked` is intentionally not a pass.",
        "",
        "| feature | app | implementation | acceptance | evidence and blocker | automated proof | real-computer proof |",
        "| --- | --- | --- | --- | --- | --- | --- |",
    ]
    for feature in feature_rows(document):
        lines.append(
            "| {id} | {app} | {implementation} | {acceptance} | {evidence} | {tests} | {computer} |".format(
                id=feature["id"],
                app=feature["app"],
                implementation=feature["implementation"],
                acceptance=feature["acceptance"],
                evidence=feature.get("notes", "not recorded").replace("|", "\\|"),
                tests="<br>".join(feature["automated_tests"]) or "none",
                computer="<br>".join(feature["computer_scenarios"]) or "none",
            )
        )
    return "\n".join(lines) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", action="store_true")
    parser.add_argument("--registry", type=Path, default=REGISTRY_PATH)
    args = parser.parse_args()
    document = load_registry(args.registry)
    outputs = {
        CATALOG_PATH: render_catalog(document),
        MATRIX_PATH: render_matrix(document),
    }
    if args.check:
        stale = [str(path.relative_to(ROOT)) for path, text in outputs.items() if not path.exists() or path.read_text("utf-8") != text]
        if stale:
            parser.error("generated feature documents are stale: " + ", ".join(stale))
        return 0
    for path, text in outputs.items():
        path.write_text(text, encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
