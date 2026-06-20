import unittest
from unittest import mock

from services import doctor


class DoctorTest(unittest.TestCase):
    def test_python_check_passes_here(self):
        ok, label, _ = doctor.check_python()
        self.assertTrue(ok)  # the test interpreter is >= 3.10
        self.assertEqual(label, "python")

    def test_required_deps_present(self):
        ok, _, detail = doctor.check_required_deps()
        self.assertTrue(ok, detail)  # the suite can't run without them anyway

    def test_required_deps_reports_missing(self):
        # pretend a hard dep is gone → check must fail and name it
        real = doctor._have
        with mock.patch.object(doctor, "_have", lambda m: False if m == "fastapi" else real(m)):
            ok, _, detail = doctor.check_required_deps()
        self.assertFalse(ok)
        self.assertIn("fastapi", detail)

    def test_optional_always_ok(self):
        ok, _, _ = doctor.check_optional_deps()
        self.assertTrue(ok)  # optional deps degrade gracefully, never block

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
        self.assertTrue(doctor.healthy())  # hard requirements all pass in CI/test env

    def test_healthy_false_when_hard_dep_missing(self):
        with mock.patch.object(doctor, "_have", lambda m: m not in ("fastapi", "uvicorn")):
            self.assertFalse(doctor.healthy())

    def test_python_check_fails_on_old_version(self):
        # fake a 3.9 interpreter — should be not ok and include the "need >= 3.10" hint
        fake_vi = mock.MagicMock()
        fake_vi.major, fake_vi.minor, fake_vi.micro = 3, 9, 0
        fake_vi.__ge__ = lambda s, o: (3, 9) >= o if isinstance(o, tuple) else NotImplemented
        fake_vi.__lt__ = lambda s, o: (3, 9) < o if isinstance(o, tuple) else NotImplemented
        with mock.patch.object(doctor.sys, "version_info", fake_vi):
            ok, label, detail = doctor.check_python()
        self.assertFalse(ok)
        self.assertIn("3.10", detail)
        self.assertEqual(label, "python")

    def test_check_secret_key_absent(self):
        # key doesn't exist → still ok (will be generated), but detail says so
        with mock.patch.object(doctor, "ROOT", doctor.ROOT / "__nonexistent_dir_xyz__"):
            ok, label, detail = doctor.check_secret_key()
        self.assertTrue(ok)  # absent key is never a hard failure
        self.assertIn("generated", detail)
        self.assertEqual(label, "at-rest encryption key")

    def test_check_secret_key_present(self):
        import tempfile

        with tempfile.TemporaryDirectory() as tmp:
            from pathlib import Path

            root = Path(tmp)
            (root / "data").mkdir()
            (root / "data" / "secret.key").write_text("dummy")
            with mock.patch.object(doctor, "ROOT", root):
                ok, label, detail = doctor.check_secret_key()
        self.assertTrue(ok)
        self.assertEqual(detail, "present")

    def test_check_data_dir_unwritable(self):
        # make mkdir+write_text blow up → check must return False, not crash
        with mock.patch("pathlib.Path.mkdir", side_effect=PermissionError("no write")):
            ok, label, detail = doctor.check_data_dir()
        self.assertFalse(ok)
        self.assertIn("NOT writable", detail)
        self.assertEqual(label, "data directory")

    def test_run_all_survives_crashing_check(self):
        # inject a check that raises — run_all must not propagate it
        def bad_check():
            raise RuntimeError("boom")

        orig = doctor._CHECKS[:]
        doctor._CHECKS.append(bad_check)
        try:
            results = doctor.run_all()
        finally:
            doctor._CHECKS[:] = orig
        # last result should be the failed check, labelled by fn name
        bad = next((r for r in results if r["label"] == "bad_check"), None)
        self.assertIsNotNone(bad)
        self.assertFalse(bad["ok"])
        self.assertIn("errored", bad["detail"])

    def test_optional_deps_detail_lists_missing(self):
        # when every optional dep is absent the detail string names them
        with mock.patch.object(doctor, "_have", lambda m: False):
            ok, label, detail = doctor.check_optional_deps()
        self.assertTrue(ok)  # still ok — they're optional
        names = [m for m, _ in doctor._OPTIONAL]
        for name in names:
            self.assertIn(name, detail)

    def test_check_endpoint_configured_db_failure(self):
        # if the DB layer can't be imported, check must return ok=False gracefully
        import builtins

        real_import = builtins.__import__

        def bad_import(name, *a, **kw):
            if name == "core.database":
                raise ImportError("no db")
            return real_import(name, *a, **kw)

        with mock.patch("builtins.__import__", side_effect=bad_import):
            ok, label, detail = doctor.check_endpoint_configured()
        self.assertFalse(ok)
        self.assertIn("check skipped", detail)
        self.assertEqual(label, "ai provider")


if __name__ == "__main__":
    unittest.main()
