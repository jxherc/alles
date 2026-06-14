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
        self.assertEqual(self.client.post("/api/push/unsubscribe", json={"endpoint": body["endpoint"]}).json(), {"ok": True})
        self.assertEqual(self.client.get("/api/push/status").json()["subscriptions"], 0)

    def test_subscribe_incomplete_400(self):
        self.assertEqual(self.client.post("/api/push/subscribe", json={"endpoint": "https://x", "keys": {}}).status_code, 400)

    def test_test_push_without_subscriptions_400(self):
        self.assertEqual(self.client.post("/api/push/test").status_code, 400)
