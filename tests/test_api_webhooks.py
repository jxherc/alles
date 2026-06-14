from tests._client import ApiTest


class WebhooksApiTest(ApiTest):
    def test_valid_events_listed(self):
        ev = self.client.get("/api/webhooks/events").json()
        self.assertIn("message", ev)
        self.assertIn("session_created", ev)

    def test_create_filters_invalid_events(self):
        w = self.client.post("/api/webhooks", json={
            "name": "hook", "url": "https://example.com/h",
            "events": ["message", "bogus", "research_done"],
        }).json()
        self.assertEqual(sorted(w["events"]), ["message", "research_done"])   # "bogus" dropped
        self.assertTrue(w["enabled"])

    def test_patch_and_delete(self):
        wid = self.client.post("/api/webhooks", json={"name": "h", "url": "https://x.io"}).json()["id"]
        r = self.client.patch(f"/api/webhooks/{wid}", json={
            "name": "h2", "url": "https://y.io", "events": ["session_renamed"], "enabled": False})
        self.assertEqual(r.json()["name"], "h2")
        self.assertEqual(r.json()["events"], ["session_renamed"])
        self.assertFalse(r.json()["enabled"])
        self.assertEqual(self.client.delete(f"/api/webhooks/{wid}").json(), {"ok": True})
        self.assertEqual(self.client.get("/api/webhooks").json(), [])

    def test_missing_404(self):
        self.assertEqual(self.client.patch("/api/webhooks/nope", json={"name": "x", "url": "u"}).status_code, 404)
        self.assertEqual(self.client.delete("/api/webhooks/nope").status_code, 404)
