from tests._client import ApiTest


class PersonasApiTest(ApiTest):
    def test_list_empty(self):
        self.assertEqual(self.client.get("/api/personas").json(), [])

    def test_create_and_default_is_exclusive(self):
        a = self.client.post("/api/personas", json={"name": "a", "is_default": True}).json()
        self.assertTrue(a["is_default"])
        # second default should knock the first one off
        self.client.post("/api/personas", json={"name": "b", "is_default": True})
        defaults = [p["name"] for p in self.client.get("/api/personas").json() if p["is_default"]]
        self.assertEqual(defaults, ["b"])

    def test_patch_and_delete(self):
        pid = self.client.post("/api/personas", json={"name": "p", "emoji": "🤖"}).json()["id"]
        r = self.client.patch(f"/api/personas/{pid}", json={"name": "p2", "system_prompt": "be terse"})
        self.assertEqual(r.json()["name"], "p2")
        self.assertEqual(r.json()["system_prompt"], "be terse")
        self.assertEqual(self.client.delete(f"/api/personas/{pid}").json(), {"ok": True})
        self.assertEqual(self.client.get("/api/personas").json(), [])

    def test_missing_404(self):
        self.assertEqual(self.client.patch("/api/personas/nope", json={"name": "x"}).status_code, 404)
        self.assertEqual(self.client.delete("/api/personas/nope").status_code, 404)

    def test_partial_patch_keeps_other_fields(self):
        # editing just the prompt must NOT wipe model / default — the old PersonaBody patch did
        pid = self.client.post("/api/personas", json={
            "name": "coder", "model": "gpt-x", "is_default": True}).json()["id"]
        r = self.client.patch(f"/api/personas/{pid}", json={"system_prompt": "be terse"}).json()
        self.assertEqual(r["system_prompt"], "be terse")
        self.assertEqual(r["model"], "gpt-x")     # untouched
        self.assertTrue(r["is_default"])          # untouched
