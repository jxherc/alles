import asyncio
import json
from unittest import mock

import httpx

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
        self.assertEqual(body["transport"], "webrtc")
        self.assertEqual(body["create_call_url"], "/api/aide/calls")
        self.assertNotIn("base_url", body)

    def test_compatible_model_without_server_credential_stays_unavailable(self):
        d = self.db()
        d.add(
            ModelEndpoint(
                name="no credential",
                base_url="https://api.openai.com/v1",
                api_key="",
                enabled=True,
                cached_models='["gpt-realtime"]',
            )
        )
        d.commit()
        status = realtime.status(d)
        d.close()
        self.assertFalse(status["available"])
        self.assertIn("authenticated", status["reason"])

    def test_declared_openai_provider_cannot_send_credentials_to_another_origin(self):
        d = self.db()
        d.add(
            ModelEndpoint(
                name="misdirected credential",
                base_url="https://example.com/v1",
                provider_id="openai",
                api_key="must-not-leave",
                enabled=True,
                cached_models='["gpt-realtime"]',
            )
        )
        d.commit()
        status = realtime.status(d)
        endpoint, model = realtime.find_webrtc_endpoint(d)
        d.close()
        self.assertFalse(status["available"])
        self.assertIsNone(endpoint)
        self.assertEqual(model, "")

    def test_malformed_openai_port_is_unavailable_instead_of_crashing_status(self):
        d = self.db()
        d.add(
            ModelEndpoint(
                name="bad port",
                base_url="https://api.openai.com:not-a-port/v1",
                provider_id="openai",
                api_key="must-not-leave",
                enabled=True,
                cached_models='["gpt-realtime"]',
            )
        )
        d.commit()
        status = realtime.status(d)
        d.close()
        self.assertFalse(status["available"])

    def test_provider_network_failure_becomes_a_safe_runtime_error(self):
        self._ep(["gpt-realtime"])
        d = self.db()
        request = httpx.Request("POST", "https://api.openai.com/v1/realtime/calls")
        with mock.patch(
            "services.realtime.httpx.AsyncClient.post",
            new=mock.AsyncMock(side_effect=httpx.ConnectError("offline", request=request)),
        ):
            with self.assertRaisesRegex(RuntimeError, "request failed"):
                endpoint, model = realtime.find_webrtc_endpoint(d)
                target = realtime.prepare_offer(
                    d, "v=0\r\noffer", endpoint_id=endpoint.id, model=model
                )
                asyncio.run(realtime.negotiate_offer(target, "v=0\r\noffer"))
        d.close()

    def test_prepared_offer_posts_the_bound_model_to_the_official_endpoint(self):
        self._ep(["gpt-realtime"])
        with self.db() as db:
            endpoint, model = realtime.find_webrtc_endpoint(db)
            target = realtime.prepare_offer(
                db, "v=0\r\noffer", endpoint_id=endpoint.id, model=model
            )
        with mock.patch(
            "services.realtime.httpx.AsyncClient.post",
            new=mock.AsyncMock(return_value=httpx.Response(201, text="v=0\r\nanswer")),
        ) as upstream:
            answer = asyncio.run(realtime.negotiate_offer(target, "v=0\r\noffer"))
        self.assertEqual(answer, "v=0\r\nanswer")
        self.assertEqual(upstream.call_args.args, ("https://api.openai.com/v1/realtime/calls",))
        kwargs = upstream.call_args.kwargs
        self.assertEqual(kwargs["headers"], {"Authorization": "Bearer sk-x"})
        session = json.loads(kwargs["files"]["session"][1])
        self.assertEqual(session["model"], "gpt-realtime")
        self.assertEqual(session["type"], "realtime")
        self.assertEqual(session["audio"]["input"]["turn_detection"]["type"], "semantic_vad")
        self.assertTrue(session["audio"]["input"]["turn_detection"]["interrupt_response"])
        self.assertTrue(session["audio"]["input"]["turn_detection"]["create_response"])
        self.assertNotIn("sk-x", repr(target))

    def test_missing_bound_model_is_not_replaced_by_another_realtime_model(self):
        self._ep(["other-realtime"])
        with self.db() as db:
            endpoint, _ = realtime.find_webrtc_endpoint(db)
            with self.assertRaisesRegex(ValueError, "realtime_unavailable"):
                realtime.prepare_offer(
                    db, "v=0\r\noffer", endpoint_id=endpoint.id, model="gpt-realtime"
                )
