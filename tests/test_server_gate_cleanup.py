"""Cleanup failures must neither leak a fixture nor hide its workflow failure."""

import importlib.util
import unittest
from pathlib import Path

_GATE_PATH = Path(__file__).with_name("pw_server_recovery.py")
_SPEC = importlib.util.spec_from_file_location("_server_recovery_cleanup_test", _GATE_PATH)
_GATE = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(_GATE)


class ServerGateCleanupTests(unittest.TestCase):
    def test_success_runs_every_release(self):
        released = []
        _GATE._run_cleanup(
            [
                (label, lambda label=label: released.append(label))
                for label in ("context", "server", "log")
            ]
        )
        self.assertEqual(released, ["context", "server", "log"])

    def test_cleanup_failure_still_releases_later_resources_and_fails(self):
        released = []
        failure = OSError("trace export failed")

        def fail():
            raise failure

        with self.assertRaises(OSError) as raised:
            _GATE._run_cleanup(
                [
                    ("trace", fail),
                    ("server", lambda: released.append("server")),
                    ("log", lambda: released.append("log")),
                ]
            )
        self.assertIs(raised.exception, failure)
        self.assertEqual(released, ["server", "log"])

    def test_workflow_error_is_preserved_and_cleanup_errors_are_visible(self):
        released = []
        failure = AssertionError("saved value differs")

        def fail():
            raise OSError("context close failed")

        with self.assertRaises(AssertionError) as raised:
            try:
                raise failure
            finally:
                _GATE._run_cleanup(
                    [
                        ("context", fail),
                        ("server", lambda: released.append("server")),
                        ("log", lambda: released.append("log")),
                    ]
                )
        self.assertIs(raised.exception, failure)
        self.assertEqual(released, ["server", "log"])
        self.assertEqual(
            failure.__notes__, ["Cleanup failed (context): OSError('context close failed')"]
        )

    def test_multiple_cleanup_errors_preserve_first_and_release_remaining(self):
        released = []
        first = OSError("trace failed")

        def fail_first():
            raise first

        def fail_second():
            raise RuntimeError("context failed")

        with self.assertRaises(OSError) as raised:
            _GATE._run_cleanup(
                [
                    ("trace", fail_first),
                    ("context", fail_second),
                    ("server", lambda: released.append("server")),
                    ("log", lambda: released.append("log")),
                ]
            )
        self.assertIs(raised.exception, first)
        self.assertEqual(released, ["server", "log"])
        self.assertEqual(
            first.__notes__, ["Cleanup also failed (context): RuntimeError('context failed')"]
        )


if __name__ == "__main__":
    unittest.main()
