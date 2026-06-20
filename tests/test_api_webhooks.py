from tests._client import ApiTest


class WebhooksApiTest(ApiTest):
    def test_valid_events_listed(self):
        ev = self.client.get("/api/webhooks/events").json()
        self.assertIn("message", ev)
        self.assertIn("session_created", ev)

    def test_create_filters_invalid_events(self):
        w = self.client.post(
            "/api/webhooks",
            json={
                "name": "hook",
                "url": "https://example.com/h",
                "events": ["message", "bogus", "research_done"],
            },
        ).json()
        self.assertEqual(sorted(w["events"]), ["message", "research_done"])  # "bogus" dropped
        self.assertTrue(w["enabled"])

    def test_patch_and_delete(self):
        wid = self.client.post("/api/webhooks", json={"name": "h", "url": "https://x.io"}).json()[
            "id"
        ]
        r = self.client.patch(
            f"/api/webhooks/{wid}",
            json={
                "name": "h2",
                "url": "https://y.io",
                "events": ["session_renamed"],
                "enabled": False,
            },
        )
        self.assertEqual(r.json()["name"], "h2")
        self.assertEqual(r.json()["events"], ["session_renamed"])
        self.assertFalse(r.json()["enabled"])
        self.assertEqual(self.client.delete(f"/api/webhooks/{wid}").json(), {"ok": True})
        self.assertEqual(self.client.get("/api/webhooks").json(), [])

    def test_missing_404(self):
        self.assertEqual(
            self.client.patch("/api/webhooks/nope", json={"name": "x", "url": "u"}).status_code, 404
        )
        self.assertEqual(self.client.delete("/api/webhooks/nope").status_code, 404)

    def test_list_empty_on_fresh_db(self):
        self.assertEqual(self.client.get("/api/webhooks").json(), [])

    def test_create_with_no_events_defaults_to_message(self):
        # default events list is ["message"] per the model
        w = self.client.post(
            "/api/webhooks", json={"name": "default", "url": "https://x.io"}
        ).json()
        self.assertEqual(w["events"], ["message"])

    def test_all_bogus_events_creates_empty_list(self):
        w = self.client.post(
            "/api/webhooks",
            json={"name": "empty", "url": "https://e.io", "events": ["foo", "bar"]},
        ).json()
        self.assertEqual(w["events"], [])

    def test_created_webhook_appears_in_list(self):
        self.client.post("/api/webhooks", json={"name": "listed", "url": "https://l.io"})
        hooks = self.client.get("/api/webhooks").json()
        self.assertTrue(any(h["name"] == "listed" for h in hooks))

    def test_disable_via_create(self):
        w = self.client.post(
            "/api/webhooks",
            json={"name": "off", "url": "https://off.io", "enabled": False},
        ).json()
        self.assertFalse(w["enabled"])

    def test_patch_re_enables_webhook(self):
        wid = self.client.post(
            "/api/webhooks", json={"name": "flip", "url": "https://flip.io", "enabled": False}
        ).json()["id"]
        r = self.client.patch(
            f"/api/webhooks/{wid}",
            json={"name": "flip", "url": "https://flip.io", "enabled": True},
        )
        self.assertTrue(r.json()["enabled"])

    def test_events_list_returns_sorted(self):
        ev = self.client.get("/api/webhooks/events").json()
        self.assertEqual(ev, sorted(ev))
