import subprocess
import sys
import unittest
from pathlib import Path

from services.feature_registry import load_registry
from services.task_routing import load_task_routing, resolved_tasks


ROOT = Path(__file__).parents[1]


class TaskRoutingTest(unittest.TestCase):
    def test_every_feature_and_scenario_has_an_executable_route(self):
        registry = load_registry()
        routing = load_task_routing()
        tasks = resolved_tasks(routing, registry)
        features = registry["features"]
        expected = len(features) + sum(len(row["computer_scenarios"]) for row in features)
        self.assertEqual(len(tasks), expected)
        self.assertNotIn("gpt-5.6-luna", {task["model"] for task in tasks})
        self.assertNotIn("max", {task["effort"] for task in tasks})

    def test_generated_routing_document_is_current(self):
        result = subprocess.run(
            [sys.executable, str(ROOT / "scripts" / "generate_task_routing.py"), "--check"],
            cwd=ROOT,
            text=True,
            capture_output=True,
            check=False,
        )
        self.assertEqual(result.returncode, 0, result.stderr or result.stdout)


if __name__ == "__main__":
    unittest.main()
