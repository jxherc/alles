#!/usr/bin/env python3
"""Render the executable model and effort assignment for every registered task."""

from __future__ import annotations

import argparse
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from services.feature_registry import load_registry  # noqa: E402
from services.task_routing import load_task_routing, resolved_tasks  # noqa: E402


OUTPUT_PATH = ROOT / "docs" / "plans" / "afterlife" / "task-model-routing.md"


def render() -> str:
    registry = load_registry()
    routing = load_task_routing()
    tasks = resolved_tasks(routing, registry)
    counts = Counter((row["model"], row["effort"]) for row in tasks)
    basis = routing["benchmark_basis"]
    lines = [
        "# Task model routing",
        "",
        f"Checked {routing['checked_on']}. Generated from `features/task-routing.json` and the live",
        "acceptance scenarios in `features/registry.json`. Edit those sources, then run",
        "`python scripts/generate_task_routing.py`. Do not hand-edit this file.",
        "",
        "## Benchmark basis",
        "",
        basis["summary"],
        "",
        "The route is therefore a hypothesis that must be calibrated on representative Alles work.",
        "Keep a cheaper route when it passes the same acceptance gate. Measure: "
        + ", ".join(basis["local_calibration_metrics"])
        + ".",
        "",
        "Sources:",
        "",
        *[f"- {source}" for source in basis["sources"]],
        "",
        "## Routing totals",
        "",
        f"- registered feature groups: {len(routing['routes'])}",
        f"- routed delivery and verification tasks: {len(tasks)}",
        *[f"- `{model}` / `{effort}`: {count}" for (model, effort), count in sorted(counts.items())],
        "",
        "`max` is not a starting route. Escalate to `gpt-5.6-sol` / `max` only when one of these",
        "conditions is recorded:",
        "",
        *[f"- {trigger}" for trigger in routing["escalation"]["triggers"]],
        "",
        "## Every registered task",
        "",
        "| feature | kind | task | model | effort |",
        "| --- | --- | --- | --- | --- |",
    ]
    for task in tasks:
        lines.append(
            f"| {task['feature_id']} | {task['kind']} | {task['task']} | "
            f"`{task['model']}` | `{task['effort']}` |"
        )
    return "\n".join(lines) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    rendered = render()
    if args.check:
        if not OUTPUT_PATH.exists() or OUTPUT_PATH.read_text("utf-8") != rendered:
            parser.error(f"generated task routing is stale: {OUTPUT_PATH.relative_to(ROOT)}")
        return 0
    OUTPUT_PATH.write_text(rendered, encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
