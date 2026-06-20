from tests._client import ApiTest


class CookbookApiTest(ApiTest):
    def test_list_empty(self):
        self.assertEqual(self.client.get("/api/cookbook").json(), [])

    def test_create_sanitizes_name(self):
        e = self.client.post(
            "/api/cookbook", json={"name": "Summarize Text", "prompt": "tl;dr this"}
        ).json()
        self.assertEqual(e["name"], "summarize-text")  # lowercased, spaces -> dashes
        self.assertEqual(e["prompt"], "tl;dr this")

    def test_patch_and_delete(self):
        eid = self.client.post("/api/cookbook", json={"name": "x", "prompt": "p"}).json()["id"]
        r = self.client.patch(
            f"/api/cookbook/{eid}", json={"name": "New Name", "prompt": "p2", "description": "d"}
        )
        self.assertEqual(r.json()["name"], "new-name")
        self.assertEqual(r.json()["description"], "d")
        self.assertEqual(self.client.delete(f"/api/cookbook/{eid}").json(), {"ok": True})
        self.assertEqual(self.client.get("/api/cookbook").json(), [])

    def test_missing_404(self):
        self.assertEqual(
            self.client.patch("/api/cookbook/nope", json={"name": "x", "prompt": "p"}).status_code,
            404,
        )
        self.assertEqual(self.client.delete("/api/cookbook/nope").status_code, 404)

    def test_description_defaults_empty(self):
        e = self.client.post("/api/cookbook", json={"name": "foo", "prompt": "bar"}).json()
        self.assertEqual(e["description"], "")

    def test_create_returns_all_fields(self):
        e = self.client.post(
            "/api/cookbook", json={"name": "test", "prompt": "do stuff", "description": "desc"}
        ).json()
        for k in ("id", "name", "prompt", "description", "created_at"):
            self.assertIn(k, e)
        self.assertTrue(e["id"])  # non-empty uid
        self.assertIn("T", e["created_at"])  # iso format has T separator

    def test_list_ordered_alphabetically(self):
        for n in ("zebra", "apple", "mango"):
            self.client.post("/api/cookbook", json={"name": n, "prompt": "p"})
        names = [e["name"] for e in self.client.get("/api/cookbook").json()]
        self.assertEqual(names, sorted(names))

    def test_list_multiple_entries(self):
        self.client.post("/api/cookbook", json={"name": "a", "prompt": "pa"})
        self.client.post("/api/cookbook", json={"name": "b", "prompt": "pb"})
        entries = self.client.get("/api/cookbook").json()
        self.assertEqual(len(entries), 2)

    def test_patch_only_changes_sent_fields(self):
        # patch updates all three writable fields; make sure prompt round-trips correctly
        eid = self.client.post(
            "/api/cookbook", json={"name": "orig", "prompt": "original prompt", "description": "d1"}
        ).json()["id"]
        updated = self.client.patch(
            f"/api/cookbook/{eid}",
            json={"name": "orig", "prompt": "new prompt", "description": "d1"},
        ).json()
        self.assertEqual(updated["prompt"], "new prompt")
        self.assertEqual(updated["description"], "d1")  # unchanged
        self.assertEqual(updated["name"], "orig")  # unchanged

    def test_name_mixed_case_and_spaces(self):
        # multiple spaces and uppercase all get flattened
        e = self.client.post("/api/cookbook", json={"name": "My Cool Recipe", "prompt": "x"}).json()
        self.assertEqual(e["name"], "my-cool-recipe")
