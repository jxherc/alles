import tempfile
from pathlib import Path

import services.skills_store as ss
from tests._client import ApiTest


class SkillsApiTest(ApiTest):
    def setUp(self):
        super().setUp()
        self._tmp = tempfile.TemporaryDirectory()
        self._orig = ss.SKILLS_DIR
        ss.SKILLS_DIR = Path(self._tmp.name)

    def tearDown(self):
        ss.SKILLS_DIR = self._orig
        self._tmp.cleanup()
        super().tearDown()

    def _create(self, name="Test Skill", desc="does stuff", when="when testing", body="steps"):
        return self.client.post(
            "/api/skills",
            json={"name": name, "description": desc, "when_to_use": when, "body": body},
        )

    def test_crud_flow(self):
        self.assertEqual(self.client.get("/api/skills").json(), [])
        r = self.client.post(
            "/api/skills",
            json={
                "name": "PDF Filler",
                "description": "fill pdf forms",
                "when_to_use": "when a pdf form needs values",
                "body": "1. open\n2. fill",
            },
        )
        self.assertEqual(r.status_code, 200)
        slug = r.json()["slug"]
        self.assertEqual(slug, "pdf-filler")

        got = self.client.get(f"/api/skills/{slug}").json()
        self.assertEqual(got["name"], "PDF Filler")
        self.assertIn("fill", got["body"])

        self.client.put(
            f"/api/skills/{slug}", json={"name": "PDF Filler", "description": "v2", "body": "x"}
        )
        self.assertEqual(self.client.get(f"/api/skills/{slug}").json()["description"], "v2")

        self.assertEqual(self.client.delete(f"/api/skills/{slug}").json(), {"ok": True})
        self.assertEqual(self.client.get("/api/skills").json(), [])

    def test_get_missing_404(self):
        self.assertEqual(self.client.get("/api/skills/nope").status_code, 404)
        self.assertEqual(self.client.delete("/api/skills/nope").status_code, 404)

    def test_match_endpoint(self):
        self.client.post(
            "/api/skills",
            json={
                "name": "Email Writer",
                "description": "draft emails",
                "when_to_use": "composing an email",
            },
        )
        m = self.client.get(
            "/api/skills/match", params={"q": "write an email to my landlord"}
        ).json()
        self.assertEqual(m["matches"][0]["slug"], "email-writer")

    def test_invalid_name_400(self):
        self.assertEqual(self.client.post("/api/skills", json={"name": "   "}).status_code, 400)

    def test_catalog_and_install(self):
        cat = self.client.get("/api/skills/catalog").json()
        self.assertGreaterEqual(len(cat), 10)
        self.assertIn("installed", cat[0])
        self.assertFalse(any(c["installed"] for c in cat))  # temp dir → nothing installed yet
        slug = cat[0]["slug"]
        self.assertEqual(
            self.client.post("/api/skills/install", json={"slugs": [slug]}).json()["installed"], 1
        )
        cat2 = self.client.get("/api/skills/catalog").json()
        self.assertTrue([c["installed"] for c in cat2 if c["slug"] == slug][0])
        self.assertTrue(any(s["slug"] == slug for s in self.client.get("/api/skills").json()))

    def test_slug_is_lowercased_and_hyphenated(self):
        r = self._create(name="My Cool Skill")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json()["slug"], "my-cool-skill")

    def test_list_returns_metadata_not_body(self):
        self._create(name="Listed Skill", body="very long body content here")
        lst = self.client.get("/api/skills").json()
        self.assertEqual(len(lst), 1)
        self.assertNotIn("body", lst[0])  # list endpoint omits body
        self.assertIn("description", lst[0])

    def test_put_updates_body(self):
        slug = self._create(name="Update Me", body="old body").json()["slug"]
        self.client.put(
            f"/api/skills/{slug}",
            json={"name": "Update Me", "description": "desc", "body": "new body"},
        )
        self.assertEqual(self.client.get(f"/api/skills/{slug}").json()["body"], "new body")

    def test_match_no_results_for_unrelated_query(self):
        self._create(name="Spreadsheet Expert", desc="excel formulas", when="analyzing data")
        m = self.client.get("/api/skills/match", params={"q": "zzzzzunrelated"}).json()
        self.assertEqual(m["matches"], [])

    def test_pin_endpoint_sorts_and_404s(self):
        self._create(name="Plain")
        pinned = self._create(name="Star").json()["slug"]
        r = self.client.post(f"/api/skills/{pinned}/pin", json={"pinned": True})
        self.assertEqual(r.status_code, 200)
        self.assertTrue(r.json()["pinned"])
        # list now sorted with the pinned one first, carrying the rank fields
        lst = self.client.get("/api/skills").json()
        self.assertEqual(lst[0]["slug"], "star")
        self.assertTrue(lst[0]["pinned"])
        self.assertIn("uses", lst[0])
        self.assertEqual(self.client.post("/api/skills/nope/pin", json={"pinned": True}).status_code, 404)

    def test_special_chars_in_name_slugified(self):
        r = self._create(name="C++ Helper!")
        self.assertEqual(r.status_code, 200)
        slug = r.json()["slug"]
        # slug should only have safe chars
        import re

        self.assertRegex(slug, r"^[a-z0-9._-]+$")
