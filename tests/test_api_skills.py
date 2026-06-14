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

    def test_crud_flow(self):
        self.assertEqual(self.client.get("/api/skills").json(), [])
        r = self.client.post("/api/skills", json={
            "name": "PDF Filler", "description": "fill pdf forms",
            "when_to_use": "when a pdf form needs values", "body": "1. open\n2. fill"})
        self.assertEqual(r.status_code, 200)
        slug = r.json()["slug"]
        self.assertEqual(slug, "pdf-filler")

        got = self.client.get(f"/api/skills/{slug}").json()
        self.assertEqual(got["name"], "PDF Filler")
        self.assertIn("fill", got["body"])

        self.client.put(f"/api/skills/{slug}", json={"name": "PDF Filler", "description": "v2", "body": "x"})
        self.assertEqual(self.client.get(f"/api/skills/{slug}").json()["description"], "v2")

        self.assertEqual(self.client.delete(f"/api/skills/{slug}").json(), {"ok": True})
        self.assertEqual(self.client.get("/api/skills").json(), [])

    def test_get_missing_404(self):
        self.assertEqual(self.client.get("/api/skills/nope").status_code, 404)
        self.assertEqual(self.client.delete("/api/skills/nope").status_code, 404)

    def test_match_endpoint(self):
        self.client.post("/api/skills", json={"name": "Email Writer", "description": "draft emails",
                                              "when_to_use": "composing an email"})
        m = self.client.get("/api/skills/match", params={"q": "write an email to my landlord"}).json()
        self.assertEqual(m["matches"][0]["slug"], "email-writer")

    def test_invalid_name_400(self):
        self.assertEqual(self.client.post("/api/skills", json={"name": "   "}).status_code, 400)
