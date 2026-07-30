#!/usr/bin/env python3
"""Generate the complete machine-readable and human-readable interaction map."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from services.interaction_map import resolved_interaction_map  # noqa: E402

JSON_PATH = ROOT / "docs" / "interaction-map.json"
MARKDOWN_PATH = ROOT / "docs" / "interaction-map.md"


def _items(values: list[str]) -> str:
    return ", ".join(f"`{value}`" for value in values) if values else "none registered"


def render_json(document: dict) -> str:
    return json.dumps(document, indent=2, sort_keys=True) + "\n"


def render_markdown(document: dict) -> str:
    lines = [
        "# Alles interaction map",
        "",
        "Generated from `features/registry.json` and `features/interaction-logic.json`. Run",
        "`python scripts/generate_interaction_map.py`; do not hand-edit this file or its JSON peer.",
        "",
        "This is an inventory, not a claim that blocked external scenarios were exercised. `external",
        "blocks or gaps` records what cannot be proved from the local environment or registry contract.",
        "",
        f"Shared control contract: `{document['shared_interaction_contract']}`. It rejects repeated",
        "activation while a control is `aria-busy=true`; individual rows retain any narrower gap.",
        "The universal visible-state vocabulary is: "
        + _items(document["shared_state_vocabulary"])
        + ".",
        "",
        "| feature | app | risk | implementation | acceptance | triggers | controls | tests |",
        "| --- | --- | --- | --- | --- | --- | --- | --- |",
    ]
    for row in document["features"]:
        lines.append(
            f"| {row['feature_id']} | {row['app']} | {row['risk']} | {row['implementation']} | "
            f"{row['acceptance']} | {'<br>'.join(row['triggers']) or 'none registered'} | "
            f"{'<br>'.join(row['control_surfaces']) or 'none registered'} | "
            f"{'<br>'.join(row['automated_tests']) or 'none registered'} |"
        )
    for row in document["features"]:
        lines.extend((f"## {row['feature_id']}", "", row["behavior"], ""))
        lines.extend(
            (
                f"- triggers: {_items(row['triggers'])}",
                f"- authority and guards: {_items(row['authority_guards'])}",
                f"- mutation or side effect: {row['mutations']}",
                f"- visible states: {_items(row['visible_states'])}",
                f"- success: {row['success']}",
                f"- failure: {row['failure']}",
                f"- recovery: {row['recovery']}",
                f"- busy and repeat: {row['busy_repeat']}",
                f"- keyboard and focus: {row['keyboard_focus']}",
                f"- control surfaces: {_items(row['control_surfaces'])}",
                f"- function surfaces: {_items([item for values in row['function_surfaces'].values() for item in values])}",
                f"- automated tests: {_items(row['automated_tests'])}",
                f"- acceptance evidence: {row['acceptance_evidence']}",
                f"- external blocks or gaps: {_items(row['external_blocks_or_gaps'])}",
                "",
            )
        )
    return "\n".join(lines)


def outputs() -> dict[Path, str]:
    document = resolved_interaction_map()
    return {JSON_PATH: render_json(document), MARKDOWN_PATH: render_markdown(document)}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    rendered = outputs()
    if args.check:
        stale = [
            str(path.relative_to(ROOT))
            for path, text in rendered.items()
            if not path.is_file() or path.read_text("utf-8") != text
        ]
        if stale:
            parser.error("generated interaction map is stale: " + ", ".join(stale))
        return 0
    for path, text in rendered.items():
        path.write_text(text, encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
