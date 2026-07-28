"""Authoritative product feature registry loading and validation.

The registry is deliberately data-only. Runtime reconciliation lives in tests so importing
this module never starts Alles or reads the owner's data directory.
"""

from __future__ import annotations

import json
from collections import Counter
from pathlib import Path
from typing import Any, Iterable


ROOT = Path(__file__).parents[1]
REGISTRY_PATH = ROOT / "features" / "registry.json"

REQUIRED_CATEGORIES = (
    "setup-security",
    "home",
    "aide",
    "andromeda",
    "plan",
    "inbox",
    "docs",
    "files-photos",
    "library",
    "health",
    "finance",
    "passwords",
    "server",
    "integrations",
    "automation",
    "localization",
    "accessibility",
    "extension-mobile",
    "backup-recovery",
    "developer-interfaces",
)

REQUIRED_FEATURE_FIELDS = (
    "id",
    "category",
    "app",
    "behavior",
    "risk",
    "dependencies",
    "platforms",
    "aide_tools",
    "automated_tests",
    "computer_scenarios",
    "implementation",
    "acceptance",
    "coverage",
)

VALID_RISKS = {"low", "medium", "high", "critical"}
VALID_IMPLEMENTATION = {"shipped", "partial", "missing", "planned"}
VALID_ACCEPTANCE = {"passed", "failed", "blocked", "unavailable", "unchecked"}
VALID_COVERAGE_KEYS = {
    "route_modules",
    "control_roots",
    "cli_commands",
    "jobs",
    "automation_actions",
    "integrations",
    "pwa_functions",
    "extension_functions",
}


class FeatureRegistryError(ValueError):
    """The registry is malformed or ambiguous."""


def load_registry(path: Path = REGISTRY_PATH) -> dict[str, Any]:
    try:
        document = json.loads(path.read_text("utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise FeatureRegistryError(f"cannot load feature registry: {exc}") from exc
    validate_registry(document)
    return document


def _require_string_list(value: Any, label: str, *, allow_empty: bool = True) -> None:
    if not isinstance(value, list) or any(not isinstance(item, str) or not item for item in value):
        raise FeatureRegistryError(f"{label} must be a list of non-empty strings")
    if not allow_empty and not value:
        raise FeatureRegistryError(f"{label} must not be empty")
    if len(value) != len(set(value)):
        raise FeatureRegistryError(f"{label} contains duplicates")


def _duplicates(values: Iterable[str]) -> list[str]:
    counts = Counter(values)
    return sorted(value for value, count in counts.items() if count > 1)


def validate_registry(document: dict[str, Any]) -> None:
    if not isinstance(document, dict) or document.get("schema_version") != 1:
        raise FeatureRegistryError("feature registry schema_version must be 1")
    categories = document.get("categories")
    if categories != list(REQUIRED_CATEGORIES):
        raise FeatureRegistryError("feature registry categories do not match the required product order")
    features = document.get("features")
    if not isinstance(features, list) or not features:
        raise FeatureRegistryError("feature registry must contain features")

    ids: list[str] = []
    all_coverage: dict[str, list[str]] = {key: [] for key in VALID_COVERAGE_KEYS}
    all_tools: list[str] = []
    for index, feature in enumerate(features):
        label = f"features[{index}]"
        if not isinstance(feature, dict):
            raise FeatureRegistryError(f"{label} must be an object")
        missing = [field for field in REQUIRED_FEATURE_FIELDS if field not in feature]
        if missing:
            raise FeatureRegistryError(f"{label} is missing: {', '.join(missing)}")
        extra = set(feature) - set(REQUIRED_FEATURE_FIELDS) - {"notes"}
        if extra:
            raise FeatureRegistryError(f"{label} has unknown fields: {', '.join(sorted(extra))}")
        feature_id = feature["id"]
        if not isinstance(feature_id, str) or not feature_id or feature_id.lower() != feature_id:
            raise FeatureRegistryError(f"{label}.id must be a non-empty lowercase string")
        ids.append(feature_id)
        if feature["category"] not in REQUIRED_CATEGORIES:
            raise FeatureRegistryError(f"{feature_id} has an unknown category")
        if feature["risk"] not in VALID_RISKS:
            raise FeatureRegistryError(f"{feature_id} has an invalid risk")
        if feature["implementation"] not in VALID_IMPLEMENTATION:
            raise FeatureRegistryError(f"{feature_id} has an invalid implementation state")
        if feature["acceptance"] not in VALID_ACCEPTANCE:
            raise FeatureRegistryError(f"{feature_id} has an invalid acceptance state")
        notes = feature.get("notes")
        if notes is not None and (not isinstance(notes, str) or not notes.strip()):
            raise FeatureRegistryError(f"{feature_id}.notes must be a non-empty string")
        if feature["acceptance"] != "unchecked" and not notes:
            raise FeatureRegistryError(f"{feature_id} needs evidence notes for its acceptance state")
        for field in ("dependencies", "platforms", "aide_tools", "automated_tests", "computer_scenarios"):
            _require_string_list(feature[field], f"{feature_id}.{field}")
        all_tools.extend(feature["aide_tools"])
        coverage = feature["coverage"]
        if not isinstance(coverage, dict) or set(coverage) != VALID_COVERAGE_KEYS:
            raise FeatureRegistryError(f"{feature_id}.coverage must contain every supported coverage key")
        for key in VALID_COVERAGE_KEYS:
            _require_string_list(coverage[key], f"{feature_id}.coverage.{key}")
            all_coverage[key].extend(coverage[key])

    duplicate_ids = _duplicates(ids)
    if duplicate_ids:
        raise FeatureRegistryError(f"duplicate feature ids: {', '.join(duplicate_ids)}")
    duplicate_tools = _duplicates(all_tools)
    if duplicate_tools:
        raise FeatureRegistryError(f"Aide tools map to multiple features: {', '.join(duplicate_tools)}")
    for key, values in all_coverage.items():
        duplicates = _duplicates(values)
        if duplicates:
            raise FeatureRegistryError(f"{key} map to multiple features: {', '.join(duplicates)}")


def ownership_map(document: dict[str, Any], surface: str) -> dict[str, str]:
    if surface == "aide_tools":
        return {
            value: feature["id"]
            for feature in document["features"]
            for value in feature["aide_tools"]
        }
    if surface not in VALID_COVERAGE_KEYS:
        raise KeyError(surface)
    return {
        value: feature["id"]
        for feature in document["features"]
        for value in feature["coverage"][surface]
    }


def feature_rows(document: dict[str, Any]) -> list[dict[str, Any]]:
    order = {category: index for index, category in enumerate(REQUIRED_CATEGORIES)}
    return sorted(document["features"], key=lambda row: (order[row["category"]], row["id"]))
