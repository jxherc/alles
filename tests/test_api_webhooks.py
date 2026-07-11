import asyncio
from types import SimpleNamespace
from unittest import mock

import httpx

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

    def test_create_generates_secret_and_status_fields(self):
        w = self.client.post("/api/webhooks", json={"name": "s", "url": "https://x.io"}).json()
        self.assertTrue(w["secret"])  # signing key minted on create
        self.assertEqual(w["last_status"], "")
        self.assertIsNone(w["last_triggered"])

    def test_sign_matches_hmac(self):
        import hashlib
        import hmac

        from routes.webhooks import _sign

        raw = b'{"a":1}'
        expect = "sha256=" + hmac.new(b"k", raw, hashlib.sha256).hexdigest()
        self.assertEqual(_sign("k", raw), expect)

    def test_test_endpoint_records_status(self):
        from unittest import mock

        wid = self.client.post("/api/webhooks", json={"name": "t", "url": "https://x.io"}).json()[
            "id"
        ]

        async def _ok(w, body):
            return ("ok", "")

        with mock.patch("routes.webhooks._deliver", _ok):
            r = self.client.post(f"/api/webhooks/{wid}/test")
        self.assertEqual(r.json()["status"], "ok")
        w = self.client.get("/api/webhooks").json()[0]
        self.assertEqual(w["last_status"], "ok")
        self.assertIsNotNone(w["last_triggered"])

    def test_test_endpoint_records_uncertain_status(self):
        from unittest import mock

        wid = self.client.post("/api/webhooks", json={"name": "t", "url": "https://x.io"}).json()[
            "id"
        ]

        async def _uncertain(w, body):
            return ("uncertain", "timed out")

        with mock.patch("routes.webhooks._deliver", _uncertain):
            r = self.client.post(f"/api/webhooks/{wid}/test")

        self.assertEqual(r.json(), {"status": "uncertain", "error": "timed out"})
        w = self.client.get("/api/webhooks").json()[0]
        self.assertEqual(w["last_status"], "uncertain")
        self.assertEqual(w["last_error"], "timed out")

    def test_test_endpoint_404(self):
        self.assertEqual(self.client.post("/api/webhooks/nope/test").status_code, 404)

    def _delivery_result(self, outcome):
        from routes import webhooks as wh

        calls = {"post": 0}

        class _Client:
            def __init__(self, *a, **k):
                pass

            async def __aenter__(self):
                return self

            async def __aexit__(self, *a):
                return False

            async def post(self, *a, **k):
                calls["post"] += 1
                if isinstance(outcome, BaseException):
                    raise outcome
                return SimpleNamespace(status_code=outcome)

        # public IP literal so the SSRF guard passes without a DNS lookup
        w = SimpleNamespace(url="http://93.184.216.34/hook", secret="", name="t")
        with mock.patch.object(wh.httpx, "AsyncClient", _Client):
            status, err = asyncio.run(wh._deliver(w, {"event": "test"}))
        return status, err, calls["post"]

    def test_deliver_does_not_retry_server_error(self):
        # A 5xx may be returned after the receiver already handled the event. Retrying can
        # duplicate the side effect, so record the result as uncertain after one attempt.
        status, err, calls = self._delivery_result(500)

        self.assertEqual(status, "uncertain")
        self.assertEqual(err, "http 500")
        self.assertEqual(calls, 1)

    def test_deliver_does_not_retry_timeout(self):
        # A read timeout does not tell us whether the receiver handled the request.
        status, err, calls = self._delivery_result(httpx.ReadTimeout("timed out"))

        self.assertEqual(status, "uncertain")
        self.assertEqual(err, "ReadTimeout")
        self.assertEqual(calls, 1)

    def test_deliver_records_client_rejection_as_error(self):
        # A 4xx is a confirmed rejection, not an ambiguous delivery.
        status, err, calls = self._delivery_result(400)

        self.assertEqual(status, "error")
        self.assertEqual(err, "http 400")
        self.assertEqual(calls, 1)
