#!/usr/bin/env python3
"""Generate the source-derived literal Alles control census."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from services.control_census import resolved_control_census  # noqa: E402

JSON_PATH = ROOT / "docs" / "control-census.json"
MARKDOWN_PATH = ROOT / "docs" / "control-census.md"


def render_json(document: dict) -> str:
    return json.dumps(document, indent=2, sort_keys=True) + "\n"


def render_markdown(document: dict) -> str:
    summary = document["summary"]
    lines = [
        "# Alles literal control census",
        "",
        "Generated from the feature registry, explicit census overrides, the static shell, and dynamic JavaScript templates.",
        "Run `python scripts/generate_control_census.py`; do not hand-edit this file or its JSON peer.",
        "",
        "This is an exhaustive source logic map, not a claim that every runtime instance or external service was exercised.",
        "Every record is assigned a bounded source authority, outcome/transition class, and recovery class. A class can say that source did not declare an authority or recovery; it never guesses a runtime result.",
        "",
        f"- static controls: {summary['static_controls']}",
        f"- dynamic templates: {summary['dynamic_templates']}",
        f"- total control records: {summary['controls']}",
        f"- discoverable activation paths: {summary['activation_paths']}",
        "- activation-path evidence: "
        + ", ".join(
            f"`{status}`={count}" for status, count in summary["activation_path_evidence"].items()
        ),
        "- visual states: "
        + ", ".join(f"`{state}`" for state in document["visual_state_vocabulary"]),
        "- evidence levels: " + ", ".join(f"`{level}`" for level in document["evidence_levels"]),
        "",
        "## How to read one record",
        "",
        "Each record names one static control or one dynamic renderer template. `source selector` is a deterministic source address; `runtime selector` is present only when source declares a stable DOM id. Dynamic templates give their instance-key semantics rather than claiming a fixed number of runtime rows. Every discoverable activation path records its event and keys, a bounded authority classification, outcome/transition class, control-source evidence, and exact existing test-control references. `test-linked-unclassified` means a test names the control but the generator cannot honestly infer which later activation line it exercised. `source-only` and `external-blocked` describe evidence scope, not runtime proof.",
        "",
        "## Control inventory",
        "",
        "| id | owner | kind | label | activation paths, provenance, and evidence | handler and path | effect and recovery | focus and states | source and evidence | flags |",
        "| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |",
    ]
    for row in document["controls"]:

        def path_summary(entry):
            keys = f" keys={','.join(entry['keys'])}" if entry["keys"] else ""
            tests = (
                ", ".join(f"{test['file']}:{test['line']}" for test in entry["evidence"]["tests"])
                or "none"
            )
            return f"{entry['modality']}:{entry['event']}{keys}; authority={entry['handler_provenance']['classification']}; handler={entry['handler_provenance']['value']}; outcome={entry['outcome']}; transition={entry['state_transition']}; evidence={entry['evidence']['status']}; tests={tests}"

        triggers = (
            "<br>".join(path_summary(entry) for entry in row["activation_paths"])
            or "no source-declared activation path"
        )
        label = row["label"]["value"] or "unknown"
        flags = ", ".join(row["flags"]) or "none"
        path = row["path"]
        handler = row["handler"]
        effect = row["effect"]
        recovery = row["recovery"]
        accessibility = row["accessibility"]
        states = row["states"]
        handler_path = f"{handler['classification']}: {handler['value']}; server={path['server_owner']}; api={path['api'] or 'none declared'}"
        effect_recovery = f"{effect['value']}; destructive={effect['destructive']}; external={effect['external']}; recovery={recovery['classification']}: {recovery['value']}"
        focus_states = f"{accessibility['focus']}; visual={','.join(states['visual'])}; outcome={','.join(states['outcome_status'])}"
        source_evidence = f"`{row['surface']['source_selector']}`; `{row['evidence']['status']}`"
        cells = (
            label,
            triggers,
            handler_path,
            effect_recovery,
            focus_states,
            source_evidence,
            flags,
        )
        escaped = [value.replace("|", "\\|").replace("\n", " ") for value in cells]
        lines.append(
            f"| `{row['id']}` | `{row['feature_owner']}` | {row['kind']} | {escaped[0]} | {escaped[1]} | {escaped[2]} | {escaped[3]} | {escaped[4]} | {escaped[5]} | {escaped[6]} |"
        )
    lines.extend(
        [
            "",
            "## Listener inventory",
            "",
            "| event | registrations discovered in static/js |",
            "| --- | ---: |",
        ]
    )
    for event, count in summary["event_listener_types"].items():
        lines.append(f"| `{event}` | {count} |")
    lines.extend(["", "## Audit flags", "", "| flag | records |", "| --- | ---: |"])
    for flag, count in summary["flags"].items():
        lines.append(f"| `{flag}` | {count} |")
    return "\n".join(lines) + "\n"


def outputs() -> dict[Path, str]:
    document = resolved_control_census()
    return {JSON_PATH: render_json(document), MARKDOWN_PATH: render_markdown(document)}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    rendered = outputs()
    if args.check:
        stale = [
            str(path.relative_to(ROOT))
            for path, value in rendered.items()
            if not path.is_file() or path.read_text("utf-8") != value
        ]
        if stale:
            parser.error("generated control census is stale: " + ", ".join(stale))
        return 0
    for path, value in rendered.items():
        path.write_text(value, encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
