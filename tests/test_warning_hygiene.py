import ast
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _deprecated_datetime_calls(tree: ast.AST) -> list[int]:
    datetime_classes = set()
    datetime_modules = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module == "datetime":
            for name in node.names:
                if name.name == "datetime":
                    datetime_classes.add(name.asname or name.name)
        elif isinstance(node, ast.Import):
            for name in node.names:
                if name.name == "datetime":
                    datetime_modules.add(name.asname or name.name)

    failures = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Attribute):
            continue
        if node.func.attr not in {"utcnow", "utcfromtimestamp"}:
            continue
        receiver = node.func.value
        direct = isinstance(receiver, ast.Name) and receiver.id in datetime_classes
        qualified = (
            isinstance(receiver, ast.Attribute)
            and receiver.attr == "datetime"
            and isinstance(receiver.value, ast.Name)
            and receiver.value.id in datetime_modules
        )
        if direct or qualified:
            failures.append(node.lineno)
    return failures


class WarningHygieneTest(unittest.TestCase):
    def test_python_sources_do_not_call_deprecated_utcnow(self):
        failures = []
        roots = [ROOT / "app.py", ROOT / "core", ROOT / "routes", ROOT / "services", ROOT / "tests"]
        paths = [roots[0]]
        for directory in roots[1:]:
            paths.extend(directory.rglob("*.py"))
        for path in paths:
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
            failures.extend(
                f"{path.relative_to(ROOT)}:{line}" for line in _deprecated_datetime_calls(tree)
            )
        self.assertEqual(
            failures,
            [],
            "deprecated UTC datetime attributes remain: " + ", ".join(failures),
        )

    def test_deprecated_datetime_check_tracks_imported_receivers_only(self):
        tree = ast.parse(
            """
from datetime import datetime as DateTime
import datetime as datetime_module
DateTime.utcnow()
datetime_module.datetime.utcfromtimestamp(0)
clock.utcnow()
"""
        )
        self.assertEqual(_deprecated_datetime_calls(tree), [4, 5])

    def test_sqlalchemy_test_engines_do_not_leak_sqlite_connections(self):
        modules = [
            "tests.test_journal",
            "tests.test_subs_analytics",
            "tests.test_money",
            "tests.test_usage",
            "tests.test_photos_search",
            "tests.test_audit_records_migration",
            "tests.test_model_catalog_migration",
            "tests.test_memory_policy.MemoryPolicyMigrationTest",
            "tests.test_recall_tools",
            "tests.test_photo_sync.PhotoSyncStoreTest",
            "tests.test_photo_sync.RunWatchTest",
            "tests.test_mcp_credentials_migration",
            "tests.test_agent_background.RuntimeTextPersistTests.test_run_persists_text_incrementally",
            "tests.test_api_backup.BackupApiTest.test_andromeda_saved_search_survives_encrypted_export_and_staging",
        ]
        with tempfile.TemporaryDirectory(prefix="alles-warning-hygiene-") as data_root:
            env = os.environ.copy()
            env["ALLES_DATA"] = data_root
            env["AUTH_ENABLED"] = "false"
            result = subprocess.run(
                [
                    sys.executable,
                    "-W",
                    "always::ResourceWarning",
                    "-m",
                    "unittest",
                    "-q",
                    *modules,
                ],
                cwd=ROOT,
                env=env,
                capture_output=True,
                text=True,
                timeout=180,
                check=False,
            )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertNotIn("unclosed database", result.stderr)


if __name__ == "__main__":
    unittest.main()
