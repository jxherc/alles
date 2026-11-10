"""Handlers that never wait run in the threadpool."""

import inspect
import os
import sys
from unittest import mock

import routes.gallery as gallery_route
import routes.sessions as sessions_route
from tests._client import ApiTest

app_module = sys.modules["app"]  # the harness imports it under a throwaway data dir


class PlainHandlerTests(ApiTest):
    def test_handlers_that_never_wait_are_plain_def(self):
        plain = [
            app_module.index,
            app_module.service_worker,
            app_module.manifest,
            app_module.opensearch,
            app_module.pwa_precache,
            app_module.api_schema,
            app_module.api_docs,
            app_module.api_docs_redirect,
            app_module.api_redoc,
            sessions_route.create_session,
            sessions_route.patch_session,
            gallery_route.upload_image,
        ]
        for fn in plain:
            self.assertFalse(inspect.iscoroutinefunction(fn), fn.__name__)

    def test_handlers_that_touch_the_loop_stay_async(self):
        import routes.aide as aide
        import routes.aide_voice as voice
        import routes.compare as compare
        import routes.jarvis as jarvis

        stay = [
            aide.photon_connect,
            voice.cancel_turn,
            voice.hangup,
            compare.start_compare,
            compare.compare_stream,
            jarvis.add_handoff,
            jarvis.retry_run,
            jarvis.submit_choice,
        ]
        for fn in stay:
            self.assertTrue(inspect.iscoroutinefunction(fn), fn.__name__)

    def test_app_shell_routes_answer_as_before(self):
        r = self.client.get("/")
        self.assertEqual(r.status_code, 200)
        self.assertIn("text/html", r.headers["content-type"])
        self.assertEqual(r.headers["cache-control"], "no-cache, no-store, must-revalidate")
        self.assertTrue(r.headers["x-alles-build"])
        sw = self.client.get("/sw.js")
        self.assertEqual(sw.status_code, 200)
        self.assertNotIn("__ALLES_BUILD__", sw.text)
        self.assertEqual(
            self.client.get("/manifest.json").headers["content-type"],
            "application/manifest+json",
        )
        os_xml = self.client.get("/opensearch.xml")
        self.assertEqual(os_xml.status_code, 200)
        self.assertIn("testserver", os_xml.text)
        urls = self.client.get("/api/pwa/precache").json()["urls"]
        self.assertEqual(urls[:2], ["/", "/manifest.json"])
        # the shell also answers on its app paths and on /health for a browser
        page = self.client.get("/docs", headers={"accept": "text/html"})
        self.assertEqual(page.status_code, 200)
        health = self.client.get("/health", headers={"accept": "text/html"})
        self.assertIn("text/html", health.headers["content-type"])
        self.assertEqual(self.client.get("/health").json(), {"ok": True})

    def test_api_docs_off_then_on(self):
        paths = ["/api/openapi.json", "/api/docs", "/api/docs/oauth2-redirect", "/api/redoc"]
        with mock.patch.dict(os.environ, {"ALLES_API_DOCS": ""}):
            for path in paths:
                self.assertEqual(self.client.get(path).status_code, 404, path)
        with mock.patch.dict(os.environ, {"ALLES_API_DOCS": "1"}):
            for path in paths:
                self.assertEqual(self.client.get(path).status_code, 200, path)
            self.assertIn("paths", self.client.get("/api/openapi.json").json())

    def test_session_create_and_patch_still_fire_their_events(self):
        fired = []

        async def fake_fire(event, data):
            fired.append(event)

        with mock.patch("services.webhook_delivery.fire", fake_fire):
            made = self.client.post("/api/sessions", json={"name": "one"})
            self.assertEqual(made.status_code, 200)
            sid = made.json()["id"]
            patched = self.client.patch(f"/api/sessions/{sid}", json={"name": "two"})
            self.assertEqual(patched.json()["name"], "two")
            self.assertEqual(
                self.client.patch("/api/sessions/nope", json={"name": "x"}).status_code, 404
            )
            self.assertEqual(
                self.client.post("/api/sessions", json={"mode": "zzz"}).status_code, 400
            )
        self.assertEqual(fired, ["session_created", "session_renamed"])
