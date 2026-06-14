from tests._client import ApiTest


class TokensApiTest(ApiTest):
    def test_create_shows_raw_once_then_never(self):
        t = self.client.post("/api/tokens", json={"name": "cli"}).json()
        self.assertTrue(t["token"].startswith("alles_"))   # raw shown only on creation
        self.assertEqual(len(t["prefix"]), 12)

        listed = self.client.get("/api/tokens").json()
        self.assertEqual(len(listed), 1)
        self.assertNotIn("token", listed[0])               # never returned again
        self.assertEqual(listed[0]["prefix"], t["prefix"])

    def test_delete(self):
        tid = self.client.post("/api/tokens", json={"name": "tmp"}).json()["id"]
        self.assertEqual(self.client.delete(f"/api/tokens/{tid}").json(), {"ok": True})
        self.assertEqual(self.client.get("/api/tokens").json(), [])

    def test_delete_missing_404(self):
        self.assertEqual(self.client.delete("/api/tokens/nope").status_code, 404)
