import tempfile
import unittest
from datetime import date
from pathlib import Path
from unittest import mock

from services import vault_md
from tests._client import ApiTest


class PeriodicPathTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.p = mock.patch.object(vault_md, "vault_dir", lambda: Path(self.tmp.name))
        self.p.start()

    def tearDown(self):
        self.p.stop()
        self.tmp.cleanup()

    def test_weekly_path(self):
        self.assertEqual(
            vault_md.periodic_path("weekly", date(2026, 6, 18)), "Periodic/2026-W25.md"
        )

    def test_monthly_path(self):
        self.assertEqual(
            vault_md.periodic_path("monthly", date(2026, 6, 18)), "Periodic/2026-06.md"
        )

    def test_weekly_year_boundary_uses_iso_year(self):
        # 2027-01-01 is ISO week 53 of 2026
        self.assertEqual(vault_md.periodic_path("weekly", date(2027, 1, 1)), "Periodic/2026-W53.md")

    def test_monthly_december(self):
        self.assertEqual(
            vault_md.periodic_path("monthly", date(2026, 12, 5)), "Periodic/2026-12.md"
        )

    def test_invalid_kind_raises(self):
        with self.assertRaises(ValueError):
            vault_md.periodic_path("yearly", date(2026, 6, 18))

    def test_default_date_is_today(self):
        self.assertRegex(vault_md.periodic_path("monthly"), r"^Periodic/\d{4}-\d{2}\.md$")

    def test_open_creates_weekly_with_template(self):
        out = vault_md.open_or_create_periodic("weekly", date(2026, 6, 18))
        self.assertEqual(out["path"], "Periodic/2026-W25.md")
        self.assertTrue(out.get("created"))
        content = vault_md.read(out["path"])["content"]
        self.assertIn("Week 25", content)
        self.assertIn("## ", content)

    def test_open_creates_monthly_with_template(self):
        out = vault_md.open_or_create_periodic("monthly", date(2026, 6, 18))
        content = vault_md.read(out["path"])["content"]
        self.assertIn("2026", content)
        self.assertIn("## ", content)

    def test_open_is_idempotent_and_nondestructive(self):
        first = vault_md.open_or_create_periodic("weekly", date(2026, 6, 18))
        vault_md.write(first["path"], "my custom week notes")
        second = vault_md.open_or_create_periodic("weekly", date(2026, 6, 18))
        self.assertTrue(second.get("existed"))
        self.assertEqual(second["path"], first["path"])
        self.assertEqual(vault_md.read(first["path"])["content"], "my custom week notes")


class PeriodicApiTests(ApiTest):
    def setUp(self):
        super().setUp()
        self.tmp = tempfile.TemporaryDirectory()
        self.vp = mock.patch.object(vault_md, "vault_dir", lambda: Path(self.tmp.name))
        self.vp.start()

    def tearDown(self):
        self.vp.stop()
        self.tmp.cleanup()
        super().tearDown()

    def test_api_weekly(self):
        r = self.client.post(
            "/api/vault-md/periodic", json={"kind": "weekly", "date": "2026-06-18"}
        )
        self.assertEqual(r.status_code, 200)
        self.assertTrue(r.json()["path"].endswith("2026-W25.md"))

    def test_api_monthly_default_date(self):
        r = self.client.post("/api/vault-md/periodic", json={"kind": "monthly"})
        self.assertEqual(r.status_code, 200)
        self.assertRegex(r.json()["path"], r"Periodic/\d{4}-\d{2}\.md")

    def test_api_invalid_kind(self):
        r = self.client.post("/api/vault-md/periodic", json={"kind": "bogus"})
        self.assertEqual(r.status_code, 400)


if __name__ == "__main__":
    unittest.main()
