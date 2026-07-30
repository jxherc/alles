import json
import subprocess
import sys
import unittest
from pathlib import Path

from services.feature_registry import load_registry
from services.interaction_map import InteractionMapError, load_logic, resolved_interaction_map

ROOT = Path(__file__).parents[1]
REQUIRED_STATES = [
    "resting",
    "hover",
    "pressed",
    "selected",
    "disabled",
    "busy",
    "invalid",
    "loading",
    "empty",
    "permission",
    "offline",
    "stale",
    "partial",
    "error",
]


class InteractionMapTest(unittest.TestCase):
    def test_every_registered_feature_and_surface_reconciles(self):
        registry = load_registry()
        document = resolved_interaction_map(registry, load_logic())
        self.assertEqual(document["shared_state_vocabulary"], REQUIRED_STATES)
        registry_by_id = {row["id"]: row for row in registry["features"]}
        self.assertEqual({row["feature_id"] for row in document["features"]}, set(registry_by_id))
        for row in document["features"]:
            feature = registry_by_id[row["feature_id"]]
            self.assertEqual(row["triggers"], feature["computer_scenarios"])
            self.assertEqual(row["control_surfaces"], feature["coverage"]["control_roots"])
            self.assertEqual(
                row["function_surfaces"],
                {
                    key: value
                    for key, value in feature["coverage"].items()
                    if key != "control_roots"
                },
            )
            self.assertEqual(row["automated_tests"], feature["automated_tests"])
            for reference in row["automated_tests"]:
                self.assertTrue((ROOT / reference).is_file(), reference)
            if feature["acceptance"] == "blocked":
                self.assertTrue(row["external_blocks_or_gaps"], row["feature_id"])

    def test_generated_documents_are_current_and_machine_readable(self):
        result = subprocess.run(
            [sys.executable, str(ROOT / "scripts" / "generate_interaction_map.py"), "--check"],
            cwd=ROOT,
            text=True,
            capture_output=True,
            check=False,
        )
        self.assertEqual(result.returncode, 0, result.stderr or result.stdout)
        document = json.loads((ROOT / "docs" / "interaction-map.json").read_text("utf-8"))
        self.assertEqual(document, resolved_interaction_map())

    def test_stale_logic_feature_is_rejected(self):
        logic = load_logic()
        logic["features"][0]["feature_id"] = "stale.feature"
        with self.assertRaises(InteractionMapError):
            resolved_interaction_map(load_registry(), logic)


if __name__ == "__main__":
    unittest.main()
