"""Load and validate benchmark-informed task routing for every registered task."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from services.feature_registry import REGISTRY_PATH, feature_rows, load_registry


ROOT = Path(__file__).parents[1]
TASK_ROUTING_PATH = ROOT / "features" / "task-routing.json"

VALID_MODELS = {"gpt-5.6-sol", "gpt-5.6-terra"}
VALID_EFFORTS = {"low", "medium", "high", "xhigh", "max"}


class TaskRoutingError(ValueError):
    """The task-routing document is malformed or out of sync."""


def _load_json(path: Path, label: str) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text("utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise TaskRoutingError(f"cannot load {label}: {exc}") from exc
    if not isinstance(value, dict):
        raise TaskRoutingError(f"{label} must be an object")
    return value


def _validate_choice(value: Any, label: str, *, allow_max: bool = False) -> None:
    if not isinstance(value, dict) or set(value) != {"model", "effort"}:
        raise TaskRoutingError(f"{label} must contain model and effort")
    if value["model"] not in VALID_MODELS:
        raise TaskRoutingError(f"{label}.model is not available")
    if value["effort"] not in VALID_EFFORTS:
        raise TaskRoutingError(f"{label}.effort is invalid")
    if value["effort"] == "max" and not allow_max:
        raise TaskRoutingError(f"{label} may not use max as its primary route")


def load_task_routing(
    path: Path = TASK_ROUTING_PATH,
    *,
    registry_path: Path = REGISTRY_PATH,
) -> dict[str, Any]:
    document = _load_json(path, "task routing")
    registry = load_registry(registry_path)
    validate_task_routing(document, registry)
    return document


def validate_task_routing(document: dict[str, Any], registry: dict[str, Any]) -> None:
    required = {
        "schema_version",
        "checked_on",
        "available_models",
        "benchmark_basis",
        "escalation",
        "routes",
    }
    if set(document) != required or document.get("schema_version") != 1:
        raise TaskRoutingError("task routing must use the complete schema_version 1 shape")
    if document["available_models"] != sorted(VALID_MODELS):
        raise TaskRoutingError("available_models must match the executable model set")

    benchmark = document["benchmark_basis"]
    if not isinstance(benchmark, dict) or set(benchmark) != {
        "summary",
        "sources",
        "local_calibration_metrics",
    }:
        raise TaskRoutingError("benchmark_basis is incomplete")
    for field in ("summary", "sources", "local_calibration_metrics"):
        value = benchmark[field]
        if (field == "summary" and (not isinstance(value, str) or not value.strip())) or (
            field != "summary"
            and (not isinstance(value, list) or not value or any(not isinstance(item, str) or not item for item in value))
        ):
            raise TaskRoutingError(f"benchmark_basis.{field} is invalid")

    escalation = document["escalation"]
    if not isinstance(escalation, dict) or set(escalation) != {"model", "effort", "triggers"}:
        raise TaskRoutingError("escalation is incomplete")
    _validate_choice({"model": escalation["model"], "effort": escalation["effort"]}, "escalation", allow_max=True)
    if escalation["effort"] != "max" or not isinstance(escalation["triggers"], list) or not escalation["triggers"]:
        raise TaskRoutingError("max effort must remain a trigger-only escalation")

    features = {row["id"]: row for row in feature_rows(registry)}
    routes = document["routes"]
    if not isinstance(routes, list):
        raise TaskRoutingError("routes must be a list")
    by_feature: dict[str, dict[str, Any]] = {}
    for index, route in enumerate(routes):
        label = f"routes[{index}]"
        if not isinstance(route, dict):
            raise TaskRoutingError(f"{label} must be an object")
        if set(route) - {"feature_id", "delivery", "verification", "overrides"}:
            raise TaskRoutingError(f"{label} has unknown fields")
        if set(route) < {"feature_id", "delivery", "verification"}:
            raise TaskRoutingError(f"{label} is incomplete")
        feature_id = route["feature_id"]
        if feature_id in by_feature:
            raise TaskRoutingError(f"duplicate route for {feature_id}")
        if feature_id not in features:
            raise TaskRoutingError(f"route points to unknown feature {feature_id}")
        _validate_choice(route["delivery"], f"{feature_id}.delivery")
        _validate_choice(route["verification"], f"{feature_id}.verification")
        scenarios = set(features[feature_id]["computer_scenarios"])
        overrides = route.get("overrides", {})
        if not isinstance(overrides, dict) or set(overrides) - scenarios:
            raise TaskRoutingError(f"{feature_id}.overrides contains an unknown scenario")
        for scenario, choice in overrides.items():
            _validate_choice(choice, f"{feature_id}.overrides[{scenario!r}]")
        by_feature[feature_id] = route
    if set(by_feature) != set(features):
        raise TaskRoutingError(
            "routing coverage mismatch: "
            f"missing={sorted(set(features) - set(by_feature))}, "
            f"stale={sorted(set(by_feature) - set(features))}"
        )


def resolved_tasks(
    routing: dict[str, Any],
    registry: dict[str, Any],
) -> list[dict[str, str]]:
    features = {row["id"]: row for row in feature_rows(registry)}
    tasks: list[dict[str, str]] = []
    for route in routing["routes"]:
        feature = features[route["feature_id"]]
        delivery_label = "finish implementation" if feature["implementation"] == "partial" else "re-audit and repair implementation"
        tasks.append(
            {
                "feature_id": feature["id"],
                "task": delivery_label,
                "kind": "delivery",
                **route["delivery"],
            }
        )
        overrides = route.get("overrides", {})
        for scenario in feature["computer_scenarios"]:
            tasks.append(
                {
                    "feature_id": feature["id"],
                    "task": scenario,
                    "kind": "verification",
                    **overrides.get(scenario, route["verification"]),
                }
            )
    return tasks
