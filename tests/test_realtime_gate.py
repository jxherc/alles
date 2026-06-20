import json

from core.database import ModelEndpoint
from services import realtime
from tests._client import ApiTest


class RealtimeGateTests(ApiTest):
    def _ep(self, models, enabled=True, name="ep"):
        d = self.db()
        e = ModelEndpoint(
            name=name,
            base_url="https://api.openai.com/v1",
            api_key="sk-x",
            enabled=enabled,
            cached_models=json.dumps(models),
        )
        d.add(e)
        d.commit()
        d.close()

    def test_no_endpoints_unavailable(self):
        d = self.db()
        st = realtime.status(d)
        d.close()
        self.assertFalse(st["available"])
        self.assertTrue(st["reason"])

    def test_non_realtime_model_unavailable(self):
        self._ep(["gpt-4o", "gpt-4o-mini"])
        d = self.db()
        self.assertFalse(realtime.status(d)["available"])
        d.close()

    def test_realtime_model_available(self):
        self._ep(["gpt-4o", "gpt-4o-realtime-preview"])
        d = self.db()
        st = realtime.status(d)
        d.close()
        self.assertTrue(st["available"])
        self.assertEqual(st["model"], "gpt-4o-realtime-preview")

    def test_disabled_endpoint_ignored(self):
        self._ep(["gpt-4o-realtime-preview"], enabled=False)
        d = self.db()
        self.assertFalse(realtime.status(d)["available"])
        d.close()

    def test_case_insensitive_match(self):
        self._ep(["GPT-Realtime"])
        d = self.db()
        self.assertTrue(realtime.status(d)["available"])
        d.close()

    def test_find_returns_ep_model(self):
        self._ep(["gpt-realtime"], name="rt")
        d = self.db()
        ep, model = realtime.find_realtime_endpoint(d)
        d.close()
        self.assertIsNotNone(ep)
        self.assertEqual(model, "gpt-realtime")

    def test_reason_present_when_unavailable(self):
        d = self.db()
        self.assertIn("realtime", realtime.status(d)["reason"].lower())
        d.close()

    # ── endpoints ──────────────────────────────────────────────────────────────
    def test_status_endpoint_shape(self):
        r = self.client.get("/api/voice/realtime/status").json()
        for k in ("available", "reason", "model"):
            self.assertIn(k, r)

    def test_session_gated_503(self):
        r = self.client.post("/api/voice/realtime/session")
        self.assertEqual(r.status_code, 503)

    def test_session_available_descriptor(self):
        self._ep(["gpt-4o-realtime-preview"])
        r = self.client.post("/api/voice/realtime/session")
        self.assertEqual(r.status_code, 200)
        body = r.json()
        self.assertEqual(body["model"], "gpt-4o-realtime-preview")
        self.assertTrue(body["base_url"])
