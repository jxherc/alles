from tests._client import ApiTest


class CookbookApiTest(ApiTest):
    def test_list_empty(self):
        self.assertEqual(self.client.get("/api/cookbook").json(), [])

    def test_create_sanitizes_name(self):
        e = self.client.post("/api/cookbook", json={"name": "Summarize Text", "prompt": "tl;dr this"}).json()
        self.assertEqual(e["name"], "summarize-text")   # lowercased, spaces -> dashes
        self.assertEqual(e["prompt"], "tl;dr this")

    def test_patch_and_delete(self):
        eid = self.client.post("/api/cookbook", json={"name": "x", "prompt": "p"}).json()["id"]
        r = self.client.patch(f"/api/cookbook/{eid}", json={"name": "New Name", "prompt": "p2", "description": "d"})
        self.assertEqual(r.json()["name"], "new-name")
        self.assertEqual(r.json()["description"], "d")
        self.assertEqual(self.client.delete(f"/api/cookbook/{eid}").json(), {"ok": True})
        self.assertEqual(self.client.get("/api/cookbook").json(), [])

    def test_missing_404(self):
        self.assertEqual(self.client.patch("/api/cookbook/nope", json={"name": "x", "prompt": "p"}).status_code, 404)
        self.assertEqual(self.client.delete("/api/cookbook/nope").status_code, 404)
