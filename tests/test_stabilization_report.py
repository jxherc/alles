import copy
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from scripts.stabilization_report import (
    BROWSER_SUITES,
    acceptance_fingerprint,
    build_report,
    source_fingerprint,
)


@patch("scripts.stabilization_report.source_fingerprint", return_value="current")
class StabilizationEvidenceTests(unittest.TestCase):
    def setUp(self):
        self.registry = {"features": [{"id": "docs"}]}
        self.census = {"controls": []}
        self.manifest = {
            "scenarios": [
                {
                    "id": "docs.edit",
                    "feature": "docs",
                    "status": "passed",
                    "required_profiles": ["desktop", "phone"],
                }
            ]
        }

    def execution(self, status="passed", profiles=None, *, day=1, outcome="passed"):
        return {
            "run_id": f"run-{day}",
            "started_at": f"2026-09-{day:02d}T00:00:00+00:00",
            "completed_at": f"2026-09-{day:02d}T00:01:00+00:00",
            "build_fingerprint": "current",
            "acceptance_fingerprint": acceptance_fingerprint(
                self.registry, self.census, self.manifest
            ),
            "status": status,
            "scenarios": [
                {
                    "scenario_id": "docs.edit",
                    "status": outcome,
                    "profiles": profiles if profiles is not None else ["desktop", "phone"],
                }
            ],
        }

    def report(self, executions):
        return build_report(self.registry, self.census, self.manifest, executions)

    def full_run(self, day):
        run = self.execution(day=day)
        run.update(suite="full", expected_gates=list(BROWSER_SUITES["full"]))
        run["results"] = [
            {
                "gate": gate,
                "status": "passed",
                "exit_code": 0,
                "build_fingerprint": "current",
                "build_fingerprint_after": "current",
                "acceptance_fingerprint": run["acceptance_fingerprint"],
                "acceptance_fingerprint_after": run["acceptance_fingerprint"],
                "server_stopped": True,
                "temporary_data_removed": True,
            }
            for gate in BROWSER_SUITES["full"]
        ]
        return run

    def test_historical_runtime_or_contract_success_cannot_certify_current_build(
        self, _fingerprint
    ):
        for field in ("build_fingerprint", "acceptance_fingerprint"):
            with self.subTest(field=field):
                run = self.execution()
                run[field] = "old"
                report = self.report([run])
                self.assertEqual(report["scenarios"][0]["status"], "untested")
                self.assertFalse(report["release_ready"])

    def test_failed_phone_profile_is_not_hidden_by_desktop_pass(self, _fingerprint):
        run = self.execution(status="failed", profiles=["desktop"])
        run["scenarios"].append(
            {"scenario_id": "docs.edit", "status": "failed", "profiles": ["phone"]}
        )
        row = self.report([run])["scenarios"][0]
        self.assertEqual(row["status"], "failed")
        self.assertEqual(row["profile_statuses"], {"desktop": "passed", "phone": "failed"})
        self.assertEqual(len(row["evidence"]), 2)

    def test_missing_profile_cannot_inherit_an_older_pass(self, _fingerprint):
        old = self.execution()
        newer = self.execution(profiles=["desktop"], day=2)
        for runs in ([old, newer], [newer, old]):
            row = self.report(runs)["scenarios"][0]
            self.assertEqual(row["status"], "untested")
            self.assertEqual(row["profile_statuses"]["phone"], "untested")

    def test_unscoped_pass_does_not_certify_required_profiles(self, _fingerprint):
        run = self.execution(profiles=[])
        self.assertEqual(self.report([run])["scenarios"][0]["status"], "untested")

    def test_latest_failure_wins_regardless_of_input_file_order(self, _fingerprint):
        passed = self.execution()
        failed = self.execution(status="failed", outcome="failed", day=2)
        for runs in ([passed, failed], [failed, passed]):
            self.assertEqual(self.report(runs)["scenarios"][0]["status"], "failed")
        rerun = self.execution(day=3)
        self.assertEqual(self.report([rerun, failed, passed])["scenarios"][0]["status"], "passed")

    def test_running_or_invalidated_execution_cannot_certify_scenarios(self, _fingerprint):
        for status in ("running", "invalidated"):
            self.assertEqual(
                self.report([self.execution(status=status)])["scenarios"][0]["status"], "untested"
            )

    def test_interrupted_or_partial_full_runs_are_not_clean_runs(self, _fingerprint):
        first, second = self.full_run(1), self.full_run(2)
        for run in (first, second):
            run["results"] = run["results"][:1]
        self.assertFalse(self.report([first, second])["release_gates"]["two_clean_full_runs"])
        for run in (first, second):
            run["status"] = "interrupted"
        self.assertFalse(self.report([first, second])["release_gates"]["two_clean_full_runs"])

    def test_two_complete_distinct_full_runs_are_required(self, _fingerprint):
        first, second = self.full_run(1), self.full_run(2)
        self.assertTrue(self.report([first, second])["release_gates"]["two_clean_full_runs"])
        self.assertFalse(self.report([first, first])["release_gates"]["two_clean_full_runs"])
        for change in (
            "missing-gate",
            "duplicate-gate",
            "changed-build",
            "changed-contract",
            "unremoved-data",
        ):
            with self.subTest(change=change):
                bad = copy.deepcopy(second)
                if change == "missing-gate":
                    bad["expected_gates"] = bad["expected_gates"][:-1]
                    bad["results"] = bad["results"][:-1]
                elif change == "duplicate-gate":
                    bad["results"][-1] = bad["results"][0]
                elif change == "changed-build":
                    bad["results"][-1]["build_fingerprint_after"] = "changed"
                elif change == "changed-contract":
                    bad["results"][-1]["acceptance_fingerprint_after"] = "changed"
                else:
                    bad["results"][-1]["temporary_data_removed"] = False
                self.assertFalse(self.report([first, bad])["release_gates"]["two_clean_full_runs"])

    def test_scenario_and_surface_success_do_not_certify_controls(self, _fingerprint):
        self.census = {
            "controls": [
                {
                    "id": "save",
                    "feature_owner": "docs",
                    "surface": "editor",
                    "label": {"value": "save"},
                }
            ]
        }
        run = self.execution()
        run["surfaces"] = [{"id": "save", "status": "passed"}]
        report = self.report([run])
        self.assertEqual(report["scenarios"][0]["status"], "passed")
        self.assertEqual(report["controls"][0]["status"], "untested")
        self.assertFalse(report["release_gates"]["all_controls_verified"])

    def test_later_failed_full_run_invalidates_the_two_clean_run_gate(self, _fingerprint):
        runs = [self.full_run(day) for day in (1, 2, 3)]
        pending = copy.deepcopy(runs[-1])
        pending["status"] = "running"
        del pending["completed_at"]
        self.assertFalse(self.report(runs[:2] + [pending])["release_gates"]["two_clean_full_runs"])
        runs[-1]["status"] = "failed"
        runs[-1]["results"][-1]["status"] = "failed"
        self.assertFalse(self.report(runs)["release_gates"]["two_clean_full_runs"])
        runs.append(self.full_run(4))
        self.assertFalse(self.report(runs)["release_gates"]["two_clean_full_runs"])
        runs.append(self.full_run(5))
        self.assertTrue(self.report(list(reversed(runs)))["release_gates"]["two_clean_full_runs"])

    def test_omitted_features_are_rejected(self, _fingerprint):
        self.registry["features"].append({"id": "vault"})
        with self.assertRaisesRegex(ValueError, "missing required workflows"):
            self.report([])


class StabilizationFingerprintTests(unittest.TestCase):
    def test_runtime_and_contract_fingerprints_are_separate_when_loaded_from_disk(self):
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            for folder in ("static", "features", "docs"):
                (root / folder).mkdir()
            registry = {"features": [{"id": "docs"}]}
            census = {"controls": []}
            manifest = {"scenarios": [{"id": "edit", "expected": "save text"}]}
            for path, value in (
                ("features/registry.json", registry),
                ("docs/control-census.json", census),
                ("features/stabilization.json", manifest),
            ):
                (root / path).write_text(json.dumps(value))
            image = root / "static/icon.png"
            image.write_bytes(b"initial")
            runtime, contract = source_fingerprint(root), acceptance_fingerprint(root=root)
            image.write_bytes(b"new icon")
            self.assertNotEqual(runtime, source_fingerprint(root))
            self.assertEqual(contract, acceptance_fingerprint(root=root))
            runtime = source_fingerprint(root)
            manifest["scenarios"][0]["expected"] = "save and recover text"
            (root / "features/stabilization.json").write_text(json.dumps(manifest))
            self.assertEqual(runtime, source_fingerprint(root))
            self.assertNotEqual(contract, acceptance_fingerprint(root=root))

    def test_runtime_images_archives_and_logs_are_hashed_but_generated_artifacts_are_not(self):
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            (root / "static").mkdir()
            for suffix in ("png", "zip", "log"):
                path = root / "static" / f"runtime.{suffix}"
                path.write_bytes(b"original")
                before = source_fingerprint(root)
                path.write_bytes(b"changed")
                self.assertNotEqual(before, source_fingerprint(root), suffix)
            (root / "tests/artifacts").mkdir(parents=True)
            before = source_fingerprint(root)
            (root / "tests/artifacts/screenshot.png").write_bytes(b"generated")
            (root / "data").mkdir()
            (root / "data/private.db").write_bytes(b"private")
            (root / ".env").write_text("synthetic private configuration")
            self.assertEqual(before, source_fingerprint(root))

    def test_contract_changes_invalidate_evidence_but_recording_outcomes_does_not(self):
        registry = {
            "features": [
                {"id": "docs", "behavior": "edit", "acceptance": "passed", "notes": "old run"}
            ]
        }
        census = {
            "controls": [
                {"id": "save", "label": {"value": "save"}, "evidence": {"status": "untested"}}
            ]
        }
        manifest = {
            "scenarios": [
                {
                    "id": "edit",
                    "expected": "retain text",
                    "required_profiles": ["desktop"],
                    "status": "untested",
                    "evidence": [],
                }
            ]
        }
        original = acceptance_fingerprint(registry, census, manifest)
        registry["features"][0].update(acceptance="failed", notes="new run")
        census["controls"][0]["evidence"] = {"status": "passed", "references": ["new"]}
        manifest["scenarios"][0].update(status="passed", evidence=["proof"])
        manifest["findings"] = [{"status": "fixed-and-verified"}]
        self.assertEqual(original, acceptance_fingerprint(registry, census, manifest))
        for field, value in (
            ("expected", "retain all text"),
            ("required_profiles", ["desktop", "phone"]),
        ):
            changed = copy.deepcopy(manifest)
            changed["scenarios"][0][field] = value
            self.assertNotEqual(original, acceptance_fingerprint(registry, census, changed))
        census["controls"][0]["label"]["value"] = "delete"
        self.assertNotEqual(original, acceptance_fingerprint(registry, census, manifest))
