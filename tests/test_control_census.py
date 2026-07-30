"""Regression coverage for the deterministic literal control census."""

from __future__ import annotations

import json
import subprocess
import sys
import unittest
from pathlib import Path

from services.control_census import (
    VISUAL_STATES,
    _with_direct_listener_paths,
    resolved_control_census,
)

ROOT = Path(__file__).parents[1]


class ControlCensusTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.document = resolved_control_census()

    def test_every_record_has_a_unique_source_address_and_complete_visual_vocabulary(self):
        controls = self.document["controls"]
        self.assertGreaterEqual(self.document["summary"]["static_controls"], 685)
        self.assertGreater(self.document["summary"]["dynamic_templates"], 0)
        self.assertEqual(len({row["id"] for row in controls}), len(controls))
        for row in controls:
            with self.subTest(control=row["id"]):
                self.assertTrue(row["surface"]["source_selector"])
                self.assertTrue(row["surface"]["source"]["file"])
                self.assertGreater(row["surface"]["source"]["line"], 0)
                self.assertEqual(row["states"]["visual"], list(VISUAL_STATES))
                self.assertIn(row["evidence"]["status"], self.document["evidence_levels"])

    def test_every_discoverable_activation_path_has_bounded_provenance_and_evidence(self):
        paths = [path for row in self.document["controls"] for path in row["activation_paths"]]
        self.assertEqual(len(paths), self.document["summary"]["activation_paths"])
        self.assertGreater(len(paths), self.document["summary"]["controls"])
        self.assertEqual(
            sum(self.document["summary"]["activation_path_evidence"].values()), len(paths)
        )
        for row in self.document["controls"]:
            for path in row["activation_paths"]:
                with self.subTest(control=row["id"], event=path["event"]):
                    self.assertIn(path["modality"], {"pointer", "keyboard", "context", "gesture"})
                    self.assertIsInstance(path["keys"], list)
                    self.assertTrue(path["handler_provenance"]["value"])
                    self.assertTrue(path["handler_provenance"]["discoverability"])
                    self.assertIn(
                        path["handler_provenance"]["classification"],
                        {
                            "inline-handler",
                            "direct-id-listener",
                            "nearest-enclosing-controller",
                            "native-link-navigation",
                            "native-field-edit",
                            "native-form-submission",
                            "no-matched-source-authority",
                        },
                    )
                    self.assertTrue(path["outcome"])
                    self.assertTrue(path["state_transition"])
                    self.assertNotIn("unknown", path["handler_provenance"]["value"].lower())
                    self.assertNotIn("unknown", path["outcome"].lower())
                    self.assertNotIn("unknown", path["state_transition"].lower())
                    evidence = path["evidence"]
                    self.assertIn(
                        evidence["status"],
                        {"source-only", "test-linked-unclassified", "external-blocked"},
                    )
                    self.assertEqual(
                        evidence["source"],
                        {
                            "file": row["surface"]["source"]["file"],
                            "line": row["surface"]["source"]["line"],
                            "kind": "control-source",
                        },
                    )
                    for test in evidence["tests"]:
                        test_path = ROOT / test["file"]
                        self.assertTrue(test_path.is_file())
                        self.assertIn(
                            row["surface"]["runtime_selector"].lstrip("#"),
                            test_path.read_text("utf-8"),
                        )
                        self.assertEqual(test["kind"], "existing-test-control-reference")
                        self.assertEqual(
                            test["claim"],
                            "control is named; activation path is not mechanically classified",
                        )

    def test_existing_shell_tests_are_linked_without_overclaiming_path_proof(self):
        drawer = next(
            row
            for row in self.document["controls"]
            if row["surface"]["runtime_selector"] == "#app-drawer-btn"
        )
        for path in drawer["activation_paths"]:
            with self.subTest(event=path["event"]):
                self.assertEqual(path["evidence"]["status"], "test-linked-unclassified")
                self.assertTrue(
                    any(
                        test["file"] == "tests/pw_kokuen_finished_surfaces.py"
                        for test in path["evidence"]["tests"]
                    )
                )
                self.assertEqual(path["handler_provenance"]["classification"], "direct-id-listener")
                self.assertIn("source-authority-dispatch", path["outcome"])
                self.assertIn("requires runtime evidence", path["state_transition"])

    def test_direct_keyboard_and_context_listeners_are_not_dropped_from_paths(self):
        paths = _with_direct_listener_paths(
            [],
            [
                "static/js/example.js:12 keydown",
                "static/js/example.js:13 contextmenu",
                "static/js/example.js:14 drop",
            ],
        )
        self.assertEqual(
            [(path["modality"], path["event"]) for path in paths],
            [
                ("keyboard", "keydown"),
                ("context", "contextmenu"),
                ("gesture", "drop"),
            ],
        )

    def test_every_source_address_still_resolves_to_its_source_file(self):
        for row in self.document["controls"]:
            with self.subTest(control=row["id"]):
                source = row["surface"]["source"]
                path = ROOT / source["file"]
                self.assertTrue(path.is_file(), path)
                self.assertLessEqual(source["line"], len(path.read_text("utf-8").splitlines()))

    def test_unmapped_owners_and_unlabeled_controls_are_explicitly_flagged(self):
        for row in self.document["controls"]:
            with self.subTest(control=row["id"]):
                if row["feature_owner"] in {"unmapped-static-owner", "unmapped-module-owner"}:
                    self.assertIn("orphan-feature-owner", row["flags"])
                if row["label"]["value"] is None:
                    self.assertIn("unknown-label", row["flags"])
                if row["surface"]["render_mode"] == "dynamic-template":
                    self.assertIn("dynamic-template", row["flags"])

    def test_every_record_has_a_bounded_authority_and_recovery_classification(self):
        for row in self.document["controls"]:
            with self.subTest(control=row["id"]):
                handler = row["handler"]
                self.assertTrue(handler["classification"])
                self.assertNotIn("unknown", handler["value"].lower())
                self.assertEqual(row["authority"]["classification"], handler["classification"])
                recovery = row["recovery"]
                self.assertTrue(recovery["classification"])
                self.assertTrue(recovery["value"])
                self.assertNotIn("unknown", recovery["value"].lower())
                if recovery["classification"] == "not-applicable":
                    self.assertTrue(recovery["reason"])

    def test_source_inference_stays_bounded_and_materially_resolved(self):
        flags = self.document["summary"]["flags"]
        self.assertEqual(flags.get("orphan-feature-owner", 0), 0)
        self.assertLessEqual(flags.get("unknown-label", 0), 80)
        inferred = [
            row
            for row in self.document["controls"]
            if row["handler"]["discoverability"] == "nearest-enclosing-function"
        ]
        self.assertGreaterEqual(len(inferred), 890)

    def test_generator_output_is_current_and_reconciles(self):
        result = subprocess.run(
            [sys.executable, str(ROOT / "scripts" / "generate_control_census.py"), "--check"],
            cwd=ROOT,
            text=True,
            capture_output=True,
            check=False,
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        generated = json.loads((ROOT / "docs" / "control-census.json").read_text("utf-8"))
        self.assertEqual(generated, self.document)


if __name__ == "__main__":
    unittest.main()
