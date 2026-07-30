"""Load and reconcile the data-only interaction logic inventory."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from services.feature_registry import REGISTRY_PATH, load_registry

ROOT = Path(__file__).parents[1]
LOGIC_PATH = ROOT / "features" / "interaction-logic.json"
COMPONENT_CONTRACT_PATH = ROOT / "design-system" / "components" / "contracts.json"
REQUIRED_FIELDS = {
    "feature_id",
    "authority_guards",
    "mutations",
    "states",
    "success",
    "failure",
    "recovery",
    "keyboard_focus",
    "gaps",
}


class InteractionMapError(ValueError):
    """The interaction logic annotations are malformed or out of registry sync."""


def load_logic(path: Path = LOGIC_PATH) -> dict[str, Any]:
    try:
        document = json.loads(path.read_text("utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise InteractionMapError(f"cannot load interaction logic: {exc}") from exc
    if not isinstance(document, dict) or document.get("schema_version") != 1:
        raise InteractionMapError("interaction logic schema_version must be 1")
    if not isinstance(document.get("contract_source"), str) or not document["contract_source"]:
        raise InteractionMapError("interaction logic needs a contract_source")
    rows = document.get("features")
    if not isinstance(rows, list) or not rows:
        raise InteractionMapError("interaction logic needs feature rows")
    seen: set[str] = set()
    for index, row in enumerate(rows):
        if not isinstance(row, dict) or set(row) != REQUIRED_FIELDS:
            raise InteractionMapError(f"interaction logic row {index} must use the complete schema")
        feature_id = row["feature_id"]
        if not isinstance(feature_id, str) or not feature_id or feature_id in seen:
            raise InteractionMapError(
                f"interaction logic row {index} has a duplicate or invalid feature_id"
            )
        seen.add(feature_id)
        for field in ("authority_guards", "states", "gaps"):
            value = row[field]
            if not isinstance(value, list) or any(
                not isinstance(item, str) or not item for item in value
            ):
                raise InteractionMapError(
                    f"{feature_id}.{field} must be a list of non-empty strings"
                )
        if not row["authority_guards"] or not row["states"]:
            raise InteractionMapError(f"{feature_id} needs authority guards and visible states")
        for field in REQUIRED_FIELDS - {"feature_id", "authority_guards", "states", "gaps"}:
            if not isinstance(row[field], str) or not row[field].strip():
                raise InteractionMapError(f"{feature_id}.{field} must be a non-empty string")
    return document


def resolved_interaction_map(
    registry: dict[str, Any] | None = None, logic: dict[str, Any] | None = None
) -> dict[str, Any]:
    registry = load_registry(REGISTRY_PATH) if registry is None else registry
    logic = load_logic(LOGIC_PATH) if logic is None else logic
    logic_by_id = {row["feature_id"]: row for row in logic["features"]}
    registry_ids = {row["id"] for row in registry["features"]}
    if registry_ids != set(logic_by_id):
        raise InteractionMapError(
            "interaction logic feature ids do not reconcile with registry: "
            f"missing={sorted(registry_ids - set(logic_by_id))}, stale={sorted(set(logic_by_id) - registry_ids)}"
        )
    contract_source = ROOT / logic["contract_source"]
    if not contract_source.is_file():
        raise InteractionMapError(
            f"shared interaction contract source is missing: {logic['contract_source']}"
        )
    try:
        state_vocabulary = json.loads(COMPONENT_CONTRACT_PATH.read_text("utf-8"))[
            "state_vocabulary"
        ]
    except (OSError, json.JSONDecodeError, KeyError, TypeError) as exc:
        raise InteractionMapError(f"cannot load the shared state vocabulary: {exc}") from exc
    rows = []
    for feature in registry["features"]:
        annotation = logic_by_id[feature["id"]]
        rows.append(
            {
                "feature_id": feature["id"],
                "app": feature["app"],
                "risk": feature["risk"],
                "implementation": feature["implementation"],
                "acceptance": feature["acceptance"],
                "behavior": feature["behavior"],
                "triggers": feature["computer_scenarios"],
                "authority_guards": annotation["authority_guards"],
                "mutations": annotation["mutations"],
                "visible_states": annotation["states"],
                "success": annotation["success"],
                "failure": annotation["failure"],
                "recovery": annotation["recovery"],
                "busy_repeat": (
                    "Shared KOKUEN controls reject re-entry while aria-busy is true; "
                    "feature-specific exceptions are recorded as gaps."
                ),
                "keyboard_focus": annotation["keyboard_focus"],
                "control_surfaces": feature["coverage"]["control_roots"],
                "function_surfaces": {
                    key: value
                    for key, value in feature["coverage"].items()
                    if key != "control_roots"
                },
                "automated_tests": feature["automated_tests"],
                "acceptance_evidence": feature.get("notes", "not recorded"),
                "external_blocks_or_gaps": annotation["gaps"],
            }
        )
    return {
        "schema_version": 1,
        "title": "Alles interaction logic map",
        "generated_from": ["features/registry.json", "features/interaction-logic.json"],
        "shared_interaction_contract": logic["contract_source"],
        "shared_state_vocabulary": state_vocabulary,
        "features": rows,
    }
