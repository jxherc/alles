from unittest import mock

from tests._client import ApiTest


async def _sent(*a, **k):
    return "sent"


async def _failed(*a, **k):
    return "failed"


async def _gone(*a, **k):
    return "gone"


class PushApiTest(ApiTest):
    def _sub(self, endpoint="https://push.example/abc"):
        return self.client.post(
            "/api/push/subscribe", json={"endpoint": endpoint, "keys": {"p256dh": "k", "auth": "a"}}
        )

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

    def test_test_push_counts_only_sent(self):
        self._sub()
        with mock.patch("routes.push.webpush.send_push", _sent):
            r = self.client.post("/api/push/test")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json()["sent"], 1)

    def test_test_push_failure_is_not_reported_sent(self):
        self._sub()
        with mock.patch("routes.push.webpush.send_push", _failed):
            r = self.client.post("/api/push/test")
        self.assertEqual(r.status_code, 502)
        self.assertEqual(r.json()["detail"], "push delivery failed")
        self.assertEqual(self.client.get("/api/push/status").json()["subscriptions"], 1)

    def test_test_push_prunes_dead_subscription(self):
        self._sub()
        with mock.patch("routes.push.webpush.send_push", _gone):
            r = self.client.post("/api/push/test")
        self.assertEqual(r.status_code, 400)
        self.assertEqual(r.json()["detail"], "no live push subscriptions registered")
        self.assertEqual(self.client.get("/api/push/status").json()["subscriptions"], 0)
