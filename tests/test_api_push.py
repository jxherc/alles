from tests._client import ApiTest


class PushApiTest(ApiTest):
    def test_status_starts_zero(self):
        self.assertEqual(self.client.get("/api/push/status").json(), {"subscriptions": 0})

    def test_subscribe_idempotent_then_unsubscribe(self):
        body = {"endpoint": "https://push.example/abc", "keys": {"p256dh": "k", "auth": "a"}}
        self.assertEqual(self.client.post("/api/push/subscribe", json=body).json(), {"ok": True})
        self.assertEqual(self.client.get("/api/push/status").json()["subscriptions"], 1)
        # same endpoint again updates in place, not a duplicate row
        self.client.post("/api/push/subscribe", json=body)
        self.assertEqual(self.client.get("/api/push/status").json()["subscriptions"], 1)
        self.assertEqual(
            self.client.post("/api/push/unsubscribe", json={"endpoint": body["endpoint"]}).json(),
            {"ok": True},
        )
        self.assertEqual(self.client.get("/api/push/status").json()["subscriptions"], 0)

    def test_subscribe_incomplete_400(self):
        self.assertEqual(
            self.client.post(
                "/api/push/subscribe", json={"endpoint": "https://x", "keys": {}}
            ).status_code,
            400,
        )

    def test_test_push_without_subscriptions_400(self):
        self.assertEqual(self.client.post("/api/push/test").status_code, 400)

    def test_vapid_key_returns_string(self):
        r = self.client.get("/api/push/vapid-key").json()
        self.assertIn("key", r)
        self.assertIsInstance(r["key"], str)

    def test_two_endpoints_count_two(self):
        self.client.post(
            "/api/push/subscribe",
            json={"endpoint": "https://push.example/x", "keys": {"p256dh": "k1", "auth": "a1"}},
        )
        self.client.post(
            "/api/push/subscribe",
            json={"endpoint": "https://push.example/y", "keys": {"p256dh": "k2", "auth": "a2"}},
        )
        self.assertEqual(self.client.get("/api/push/status").json()["subscriptions"], 2)

    def test_unsubscribe_nonexistent_ok(self):
        r = self.client.post(
            "/api/push/unsubscribe", json={"endpoint": "https://nope.example/ghost"}
        )
        self.assertEqual(r.json(), {"ok": True})

    def test_missing_p256dh_400(self):
        r = self.client.post(
            "/api/push/subscribe", json={"endpoint": "https://x", "keys": {"auth": "a"}}
        )
        self.assertEqual(r.status_code, 400)

    def test_missing_auth_400(self):
        r = self.client.post(
            "/api/push/subscribe", json={"endpoint": "https://x", "keys": {"p256dh": "k"}}
        )
        self.assertEqual(r.status_code, 400)

    def test_subscribe_updates_keys_in_place(self):
        ep = "https://push.example/update"
        self.client.post(
            "/api/push/subscribe", json={"endpoint": ep, "keys": {"p256dh": "k1", "auth": "a1"}}
        )
        self.client.post(
            "/api/push/subscribe", json={"endpoint": ep, "keys": {"p256dh": "k2", "auth": "a2"}}
        )
        # still just one row
        self.assertEqual(self.client.get("/api/push/status").json()["subscriptions"], 1)
