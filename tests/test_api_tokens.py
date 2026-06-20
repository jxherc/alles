from tests._client import ApiTest


class TokensApiTest(ApiTest):
    def test_create_shows_raw_once_then_never(self):
        t = self.client.post("/api/tokens", json={"name": "cli"}).json()
        self.assertTrue(t["token"].startswith("alles_"))  # raw shown only on creation
        self.assertEqual(len(t["prefix"]), 12)

        listed = self.client.get("/api/tokens").json()
        self.assertEqual(len(listed), 1)
        self.assertNotIn("token", listed[0])  # never returned again
        self.assertEqual(listed[0]["prefix"], t["prefix"])

    def test_delete(self):
        tid = self.client.post("/api/tokens", json={"name": "tmp"}).json()["id"]
        self.assertEqual(self.client.delete(f"/api/tokens/{tid}").json(), {"ok": True})
        self.assertEqual(self.client.get("/api/tokens").json(), [])

    def test_delete_missing_404(self):
        self.assertEqual(self.client.delete("/api/tokens/nope").status_code, 404)

    def test_multiple_tokens_listed(self):
        self.client.post("/api/tokens", json={"name": "t1"})
        self.client.post("/api/tokens", json={"name": "t2"})
        listed = self.client.get("/api/tokens").json()
        self.assertEqual(len(listed), 2)
        names = {t["name"] for t in listed}
        self.assertEqual(names, {"t1", "t2"})

    def test_prefix_matches_token_start(self):
        t = self.client.post("/api/tokens", json={"name": "pfx"}).json()
        self.assertTrue(t["token"].startswith(t["prefix"]))

    def test_token_has_id_field(self):
        t = self.client.post("/api/tokens", json={"name": "id-check"}).json()
        self.assertIn("id", t)
        self.assertTrue(t["id"])

    def test_listed_tokens_have_no_raw_token(self):
        self.client.post("/api/tokens", json={"name": "a"})
        self.client.post("/api/tokens", json={"name": "b"})
        for t in self.client.get("/api/tokens").json():
            self.assertNotIn("token", t)

    def test_delete_one_leaves_others(self):
        t1 = self.client.post("/api/tokens", json={"name": "keep"}).json()
        t2 = self.client.post("/api/tokens", json={"name": "drop"}).json()
        self.client.delete(f"/api/tokens/{t2['id']}")
        listed = self.client.get("/api/tokens").json()
        self.assertEqual(len(listed), 1)
        self.assertEqual(listed[0]["id"], t1["id"])

    def test_created_at_present(self):
        t = self.client.post("/api/tokens", json={"name": "ts"}).json()
        self.assertIn("created_at", t)
        self.assertIsNotNone(t["created_at"])
