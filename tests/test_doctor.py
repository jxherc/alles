import unittest
from unittest import mock

from services import doctor


class DoctorTest(unittest.TestCase):
    def test_python_check_passes_here(self):
        ok, label, _ = doctor.check_python()
        self.assertTrue(ok)              # the test interpreter is >= 3.10
        self.assertEqual(label, "python")

    def test_required_deps_present(self):
        ok, _, detail = doctor.check_required_deps()
        self.assertTrue(ok, detail)      # the suite can't run without them anyway

    def test_required_deps_reports_missing(self):
        # pretend a hard dep is gone → check must fail and name it
        real = doctor._have
        with mock.patch.object(doctor, "_have", lambda m: False if m == "fastapi" else real(m)):
            ok, _, detail = doctor.check_required_deps()
        self.assertFalse(ok)
        self.assertIn("fastapi", detail)

    def test_optional_always_ok(self):
        ok, _, _ = doctor.check_optional_deps()
        self.assertTrue(ok)              # optional deps degrade gracefully, never block

    def test_data_dir_writable(self):
        ok, _, _ = doctor.check_data_dir()
        self.assertTrue(ok)

    def test_run_all_shape_and_healthy(self):
        checks = doctor.run_all()
        labels = {c["label"] for c in checks}
        self.assertIn("required dependencies", labels)
        self.assertIn("data directory", labels)
        for c in checks:
            self.assertEqual(set(c), {"ok", "label", "detail"})
        self.assertTrue(doctor.healthy())   # hard requirements all pass in CI/test env

    def test_healthy_false_when_hard_dep_missing(self):
        with mock.patch.object(doctor, "_have", lambda m: m not in ("fastapi", "uvicorn")):
            self.assertFalse(doctor.healthy())


if __name__ == "__main__":
    unittest.main()
