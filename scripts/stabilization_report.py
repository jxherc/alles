#!/usr/bin/env python3
"""Join required workflows and the control inventory without inventing runtime proof."""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
from collections import Counter
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from services.control_census import resolved_control_census  # noqa: E402

STATUSES = {"untested", "failed", "passed", "blocked"}
SMOKE_GATES = ("smoke-desktop", "smoke-phone")
SURFACE_GATES = tuple(
    f"surfaces-{device}-{theme}" for device in ("desktop", "phone") for theme in ("dark", "light")
)
# Shared by execution and acceptance: a result cannot redefine what a full run requires.
BROWSER_SUITES = {
    "ownership": ("style-ownership", "settings-recovery", "settings-panes", "files-workflows"),
    "smoke": SMOKE_GATES,
    "surfaces": SURFACE_GATES,
    "daily": (
        "minimal-workflows",
        "docs-editor-loading",
        "docs-workbench-navigation",
        "plan-workflows",
        "plan-recovery",
        "calendar-workflows",
        "mail-calendar-capture",
        "calendar-metadata-picker",
        "files-workflows",
        "files-upload-recovery",
        "files-transfer-clearance",
        "home-reminders",
        "home-capture",
        "home-day-draft",
        "home-record-links",
        "home-record-recovery",
        "home-preferences",
        "today-capture-confirm",
        "home-route-parity",
        "home-route-parity-off",
        "home-suggestions",
        "shell-command-shortcuts",
        "shell-app-name",
    ),
    "setup": ("setup-auth",),
    "settings": (
        "settings-recovery",
        "settings-panes",
        "settings-language-badges",
        "settings-selected",
        "settings-context",
    ),
    "administration": (
        "server-recovery",
        "settings-recovery",
        "settings-language-badges",
        "settings-selected",
        "settings-context",
        "vault-backup",
    ),
    "calendar": ("calendar-workflows", "calendar-metadata-picker", "mail-calendar-capture"),
    "recurring": (
        "finance-recurring-create",
        "finance-recurring-edit",
        "finance-recurring-repair",
    ),
    "files": ("files-workflows", "files-upload-recovery", "files-transfer-clearance"),
    "gallery": ("gallery-workflows", "aide-creations"),
    "creations": ("aide-creations",),
    "pwa": ("pwa-offline", "pwa-storage", "pwa-rejection"),
    "assistant": (
        "andromeda-cancellation",
        "aide-continuity",
        "aide-composer",
        "aide-image-retry",
        "aide-questions",
        "aide-document-safety",
        "aide-creations",
    ),
    "questions": ("aide-questions",),
    "specialist": (
        "health-workflows",
        "finance-workflows",
        "finance-networth-history",
        "finance-recurring-create",
        "finance-recurring-edit",
        "finance-recurring-repair",
        "library-workflows",
        "inbox-workflows",
        "vault-backup",
    ),
    "full": (
        "style-ownership",
        "settings-panes",
        *SMOKE_GATES,
        "cleanup-regressions",
        "minimal-workflows",
        "docs-editor-loading",
        "docs-workbench-navigation",
        "plan-workflows",
        "plan-recovery",
        "calendar-workflows",
        "mail-calendar-capture",
        "calendar-metadata-picker",
        "files-workflows",
        "files-upload-recovery",
        "files-transfer-clearance",
        "home-reminders",
        "home-capture",
        "home-day-draft",
        "home-record-links",
        "home-record-recovery",
        "home-preferences",
        "today-capture-confirm",
        "home-route-parity",
        "home-route-parity-off",
        "home-suggestions",
        "shell-command-shortcuts",
        "shell-app-name",
        "setup-auth",
        "settings-recovery",
        "settings-language-badges",
        "settings-selected",
        "settings-context",
        "server-recovery",
        "gallery-workflows",
        "aide-creations",
        "andromeda-cancellation",
        "aide-continuity",
        "aide-composer",
        "aide-image-retry",
        "aide-questions",
        "aide-document-safety",
        "health-workflows",
        "finance-workflows",
        "finance-networth-history",
        "finance-recurring-create",
        "finance-recurring-edit",
        "finance-recurring-repair",
        "library-workflows",
        "inbox-workflows",
        "vault-backup",
        "pwa-offline",
        "pwa-storage",
        "pwa-rejection",
        *SURFACE_GATES,
    ),
}


def source_fingerprint(root: Path = ROOT) -> str:
    """Include dirty and new runtime/test files, but never private data or .env."""
    digest = hashlib.sha256()
    paths = [
        root / name
        for name in ("app.py", "cli.py", "requirements.txt", "requirements.lock", "pyproject.toml")
    ]
    for folder in ("core", "routes", "services", "static", "tests", "scripts", ".github"):
        paths.extend(
            path
            for path in (root / folder).rglob("*")
            if path.is_file()
            and not path.is_symlink()
            and "__pycache__" not in path.parts
            and path.suffix != ".pyc"
            and not {"artifacts", "test-results", "playwright-report"}.intersection(
                path.relative_to(root / folder).parts[:-1]
            )
        )
    for path in sorted(set(paths)):
        if path.is_file():
            digest.update(str(path.relative_to(root)).encode())
            digest.update(b"\0")
            digest.update(path.read_bytes())
            digest.update(b"\0")
    return digest.hexdigest()


def _contract_data(value):
    """Remove recorded outcomes, retaining requirements and required device profiles."""
    if isinstance(value, dict):
        return {
            key: _contract_data(item)
            for key, item in value.items()
            if key not in {"status", "evidence", "acceptance", "notes"}
        }
    if isinstance(value, list):
        return [_contract_data(item) for item in value]
    return value


def acceptance_fingerprint(
    registry: dict | None = None,
    census: dict | None = None,
    manifest: dict | None = None,
    *,
    root: Path = ROOT,
) -> str:
    if registry is None:
        registry = json.loads((root / "features/registry.json").read_text())
    if census is None:
        census = (
            resolved_control_census()
            if root == ROOT
            else json.loads((root / "docs/control-census.json").read_text())
        )
    if manifest is None:
        manifest = json.loads((root / "features/stabilization.json").read_text())
    contract = _contract_data(
        {
            "features": registry["features"],
            "controls": census["controls"],
            "scenarios": manifest["scenarios"],
            "additional_surfaces": manifest.get("additional_surfaces", []),
            "browser_suites": BROWSER_SUITES,
        }
    )
    return hashlib.sha256(
        json.dumps(contract, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def _timestamp(value) -> datetime | None:
    try:
        parsed = datetime.fromisoformat(value)
        return parsed if parsed.tzinfo is not None else None
    except (TypeError, ValueError):
        return None


def _profiles(result: dict) -> list[str]:
    profiles = result.get("profiles", [result["profile"]] if result.get("profile") else [])
    if not isinstance(profiles, list) or any(not isinstance(p, str) or not p for p in profiles):
        raise ValueError("profiles must be a list of nonempty names")
    return list(dict.fromkeys(profiles))


def _outcome(results: list[dict]) -> str:
    statuses = {result["status"] for result in results}
    # A contradictory result from the same execution must not hide its failure.
    for status in ("failed", "blocked", "untested"):
        if status in statuses:
            return status
    return "passed" if statuses == {"passed"} else "untested"


def _apply_evidence(row: dict, executions: list[dict], collection: str, id_key: str) -> None:
    required = row.get("required_profiles", [])
    if not isinstance(required, list) or any(not isinstance(p, str) or not p for p in required):
        raise ValueError("required_profiles must be a list of nonempty names")
    latest = []
    latest_time = None
    row["evidence"] = []
    for execution in executions:
        results = [r for r in execution.get(collection, []) if r.get(id_key) == row["id"]]
        if not results:
            continue
        for result in results:
            if result.get("status") not in STATUSES:
                raise ValueError("result must name an actual execution outcome")
            _profiles(result)
            row["evidence"].append(
                {
                    **result,
                    "execution_run_id": execution.get("run_id"),
                    "execution_completed_at": execution["completed_at"],
                }
            )
        timestamp = _timestamp(execution["completed_at"])
        if latest_time is None or timestamp > latest_time:
            latest, latest_time = results, timestamp
        elif timestamp == latest_time:
            latest.extend(results)
    if not latest:
        return
    if required:
        row["profile_statuses"] = {
            profile: _outcome([r for r in latest if profile in _profiles(r)])
            for profile in required
        }
        # Unscoped failures still matter; unscoped successes cannot cover named profiles.
        failures = [r for r in latest if not _profiles(r) and r["status"] != "passed"]
        row["status"] = _outcome(
            [{"status": status} for status in row["profile_statuses"].values()] + failures
        )
    else:
        row["status"] = _outcome(latest)


def _clean_full_run(run: dict) -> bool:
    expected = BROWSER_SUITES["full"]
    results = run.get("results", [])
    started, completed = _timestamp(run.get("started_at")), _timestamp(run.get("completed_at"))
    return bool(
        run.get("suite") == "full"
        and run.get("status") == "passed"
        and run.get("run_id")
        and started
        and completed
        and completed >= started
        and run.get("expected_gates") == list(expected)
        and len(results) == len(expected)
        and {r.get("gate") for r in results} == set(expected)
        and all(
            r.get("status") == "passed"
            and r.get("exit_code") == 0
            and r.get("build_fingerprint") == run["build_fingerprint"]
            and r.get("build_fingerprint_after") == run["build_fingerprint"]
            and r.get("acceptance_fingerprint") == run["acceptance_fingerprint"]
            and r.get("acceptance_fingerprint_after") == run["acceptance_fingerprint"]
            and r.get("server_stopped") is True
            and r.get("temporary_data_removed") is True
            for r in results
        )
    )


def build_report(registry: dict, census: dict, manifest: dict, executions: list[dict]) -> dict:
    features = {row["id"]: row for row in registry["features"]}
    features.update({row["id"]: row for row in manifest.get("additional_surfaces", [])})
    fingerprint = source_fingerprint()
    contract = acceptance_fingerprint(registry, census, manifest)
    matching = [
        run
        for run in executions
        if run.get("build_fingerprint") == fingerprint
        and run.get("acceptance_fingerprint") == contract
        and run.get("status") != "invalidated"
    ]
    current = [
        run
        for run in matching
        if run.get("status") in {"passed", "failed", "interrupted"}
        and _timestamp(run.get("completed_at")) is not None
    ]
    scenarios = []
    ids = set()
    for source in manifest["scenarios"]:
        row = dict(source)
        if row["id"] in ids or row["feature"] not in features:
            raise ValueError(f"duplicate or unowned scenario: {row['id']}")
        ids.add(row["id"])
        if row["status"] not in STATUSES:
            raise ValueError(f"invalid status: {row['status']}")
        if row["status"] == "passed":
            row["status"] = "untested"
        _apply_evidence(row, current, "scenarios", "scenario_id")
        scenarios.append(row)
    missing = set(features) - {row["feature"] for row in scenarios}
    if missing:
        raise ValueError(f"features missing required workflows: {sorted(missing)}")
    controls = [
        {
            "id": control["id"],
            "feature": control["feature_owner"],
            "surface": control["surface"],
            "label": control["label"]["value"],
            "required_profiles": control.get("required_profiles", []),
            "status": "untested",
            "expected": "activation follows its label, exposes state, and preserves recovery",
        }
        for control in census["controls"]
    ]
    for control in controls:
        _apply_evidence(control, current, "controls", "control_id")
    control_ids = {row["id"] for row in controls}
    unmapped_scenarios = sorted(
        {
            result["scenario_id"]
            for run in current
            for result in run.get("scenarios", [])
            if result.get("scenario_id") and result["scenario_id"] not in ids
        }
    )
    unmapped_controls = sorted(
        {
            result["control_id"]
            for run in current
            for result in run.get("controls", [])
            if result.get("control_id") and result["control_id"] not in control_ids
        }
    )
    full_runs = {}
    for run in matching:
        if (
            run.get("suite") == "full"
            and run.get("run_id")
            and (_timestamp(run.get("completed_at")) or _timestamp(run.get("started_at")))
        ):
            full_runs.setdefault(run["run_id"], []).append(run)
    latest_full = sorted(
        full_runs.values(),
        key=lambda copies: max(
            _timestamp(run.get("completed_at")) or _timestamp(run.get("started_at"))
            for run in copies
        ),
    )[-2:]
    release_gates = {
        "all_execution_results_mapped": not unmapped_scenarios and not unmapped_controls,
        "all_required_scenarios": bool(scenarios)
        and all(row["status"] == "passed" for row in scenarios),
        "all_controls_verified": bool(controls)
        and all(row["status"] == "passed" for row in controls),
        "two_clean_full_runs": len(latest_full) == 2
        and all(_clean_full_run(run) for copies in latest_full for run in copies),
        "no_open_blocking_findings": not any(
            finding.get("severity") in {"critical", "high"}
            and finding.get("status") != "fixed-and-verified"
            for finding in manifest.get("findings", [])
        ),
    }
    return {
        "schema_version": 2,
        "build_fingerprint": fingerprint,
        "acceptance_fingerprint": contract,
        "release_ready": all(release_gates.values()),
        "release_gates": release_gates,
        "note": "scenario success never automatically certifies every control in its feature",
        "summary": {
            "features": len(features),
            "controls": len(controls),
            "scenarios": dict(Counter(row["status"] for row in scenarios)),
            "unmapped_control_owners": sorted({row["feature"] for row in controls} - set(features)),
            "unmapped_scenario_results": unmapped_scenarios,
            "unmapped_control_results": unmapped_controls,
        },
        "scenarios": scenarios,
        "controls": controls,
        "findings": manifest.get("findings", []),
        "executions": executions,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--results", type=Path, nargs="*", default=[])
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    report = build_report(
        json.loads((ROOT / "features/registry.json").read_text()),
        resolved_control_census(),
        json.loads((ROOT / "features/stabilization.json").read_text()),
        [json.loads(path.read_text()) for path in args.results],
    )
    report["revision"] = subprocess.check_output(
        ["git", "rev-parse", "HEAD"], cwd=ROOT, text=True
    ).strip()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps(report["summary"]))


if __name__ == "__main__":
    main()
