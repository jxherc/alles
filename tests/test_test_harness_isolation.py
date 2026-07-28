import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

# Deliberately import settings first. This is the ordering that previously froze settings.json on
# the normal repo data directory before the API harness selected a throwaway ALLES_DATA.
import core.settings as settings
from services import secretstore
from tests import (
    _client,  # noqa: F401, E402
    browser_gate_safety,
)


class TestHarnessIsolationTest(unittest.TestCase):
    def test_browser_gate_server_proof_must_match_the_local_run(self):
        class Response:
            headers = {"X-Alles-Test-Run-ID": "owned-test-run"}

            @staticmethod
            def geturl():
                return "http://127.0.0.1:6769/health"

            def __enter__(self):
                return self

            def __exit__(self, *_args):
                return False

        with patch.object(browser_gate_safety, "_open_without_redirects", return_value=Response()):
            browser_gate_safety.require_server_ownership("http://127.0.0.1:6769", "owned-test-run")
            with self.assertRaisesRegex(RuntimeError, "does not match"):
                browser_gate_safety.require_server_ownership(
                    "http://127.0.0.1:6769", "different-test-run"
                )

        redirected = Response()
        redirected.geturl = lambda: "http://127.0.0.1:9999/health"
        with (
            patch.object(
                browser_gate_safety,
                "_open_without_redirects",
                return_value=redirected,
            ),
            self.assertRaisesRegex(RuntimeError, "redirected"),
        ):
            browser_gate_safety.require_server_ownership("http://127.0.0.1:6769", "owned-test-run")

    def test_package_bootstrap_precedes_application_imports_in_test_modules(self):
        with tempfile.TemporaryDirectory(prefix="alles-owner-root-") as owner:
            env = os.environ.copy()
            env.update({"ALLES_DATA": owner})
            env.pop("ALLES_TEST_DATA", None)
            env.pop("ALLES_TEST_RUN_ID", None)
            result = subprocess.run(
                [
                    sys.executable,
                    "-c",
                    "import tests.test_actual_finance_canonical; "
                    "from core.settings import data_dir; print(data_dir())",
                ],
                cwd=Path(__file__).parents[1],
                env=env,
                text=True,
                capture_output=True,
                check=True,
            )
        isolated = Path(result.stdout.strip()).resolve()
        self.assertNotEqual(isolated, Path(owner).resolve())
        self.assertIn("alles-tests-bootstrap-", isolated.name)

    def test_early_settings_import_is_rebound_to_the_throwaway_data_root(self):
        root = Path(os.environ["ALLES_DATA"]).resolve()
        self.assertEqual(settings._SETTINGS_FILE.resolve(), root / "settings.json")
        self.assertEqual(secretstore._key_file().resolve(), root / "secret.key")
        self.assertNotEqual(root, (Path(__file__).parents[1] / "data").resolve())

    def test_explicit_owned_temporary_data_root_is_preserved(self):
        with tempfile.TemporaryDirectory(prefix="alles-owned-api-test-") as raw:
            root = Path(raw).resolve()
            run_id = "owned-test-run"
            (root / ".alles-test-owner").write_text(run_id, encoding="utf-8")
            with patch.dict(
                os.environ,
                {
                    "ALLES_DATA": str(root),
                    "ALLES_TEST_DATA": "1",
                    "ALLES_TEST_RUN_ID": run_id,
                },
                clear=False,
            ):
                self.assertEqual(_client._validated_inherited_test_root(), root)

    def test_unproved_inherited_data_root_is_never_reused(self):
        with patch.dict(
            os.environ,
            {"ALLES_DATA": str(Path(__file__).parents[1] / "data")},
            clear=False,
        ):
            os.environ.pop("ALLES_TEST_DATA", None)
            os.environ.pop("ALLES_TEST_RUN_ID", None)
            self.assertIsNone(_client._validated_inherited_test_root())

    def test_phase7_browser_gate_requires_an_explicit_temp_root_sentinel(self):
        source = (Path(__file__).parent / "pw_phase7_files_real.py").read_text(encoding="utf-8")
        self.assertIn("def _require_throwaway_data_root", source)
        self.assertIn("ALLES_TEST_DATA", source)
        self.assertIn("ALLES_TEST_RUN_ID", source)
        self.assertIn(".alles-test-owner", source)
        self.assertIn("owner_file.read_text", source)
        self.assertIn("tempfile.gettempdir()", source)
        self.assertIn("require_server_ownership", source)
        self.assertNotIn("wait_for_timeout(400)", source)
        guard_call = "\n    _require_throwaway_data_root()\n"
        self.assertIn(guard_call, source)
        self.assertLess(source.index(guard_call), source.index('files = DATA / "files"'))

    def test_phase8_browser_gate_requires_the_shared_server_ownership_proof(self):
        source = (Path(__file__).parent / "pw_phase8_specialist_real.py").read_text(
            encoding="utf-8"
        )
        self.assertIn("ALLES_TEST_DATA", source)
        self.assertIn("ALLES_TEST_RUN_ID", source)
        self.assertIn(".alles-test-owner", source)
        self.assertIn("require_server_ownership", source)
        guard_call = "\n    _require_throwaway_data_root()\n"
        self.assertIn(guard_call, source)
        self.assertLess(source.index(guard_call), source.index("OUTPUT.mkdir"))

    def test_aide_shell_browser_gate_requires_owned_temp_data_before_uploads(self):
        source = (Path(__file__).parent / "pw_afterlife_aide_shell.py").read_text(encoding="utf-8")
        self.assertIn("ALLES_TEST_DATA", source)
        self.assertIn("ALLES_TEST_RUN_ID", source)
        self.assertIn(".alles-test-owner", source)
        self.assertIn("require_server_ownership", source)
        guard_call = "\n    _require_throwaway_data_root()\n"
        self.assertIn(guard_call, source)
        self.assertLess(
            source.index(guard_call),
            source.index("set_input_files"),
        )

    def test_native_install_gate_requires_separate_data_and_home_sentinels(self):
        source = (Path(__file__).parent / "pw_native_install_current_host.py").read_text(
            encoding="utf-8"
        )
        self.assertIn('(DATA / ".alles-test-owner").read_text', source)
        self.assertIn('(HOME / ".alles-test-owner").read_text', source)
        guard_call = "\n    _verify_owned_root()\n"
        self.assertIn(guard_call, source)
        self.assertLess(source.index(guard_call), source.index("native_install.platform_layout"))


if __name__ == "__main__":
    unittest.main()
