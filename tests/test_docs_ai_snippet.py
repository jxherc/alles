"""ui-3i — the /ai-snippet route powers the context-menu AI actions (rewrite /
summarize / fix) on the *selected* text only."""

import json
from unittest import mock

from core.database import ModelEndpoint
from tests._client import ApiTest


class AiSnippetTests(ApiTest):
    def _endpoint(self):
        d = self.db()
        d.add(
            ModelEndpoint(
                name="T",
                base_url="http://localhost",
                api_key="k",
                enabled=True,
                cached_models=json.dumps(["m1"]),
            )
        )
        d.commit()
        d.close()

    def test_no_endpoint_400(self):
        r = self.client.post("/api/vault-md/ai-snippet", json={"text": "hi", "action": "rewrite"})
        self.assertEqual(r.status_code, 400)

    def test_empty_text_400(self):
        self._endpoint()
        r = self.client.post("/api/vault-md/ai-snippet", json={"text": "   ", "action": "rewrite"})
        self.assertEqual(r.status_code, 400)

    def test_rewrite_returns_model_text(self):
        self._endpoint()
        with mock.patch(
            "services.llm.simple_complete", new=mock.AsyncMock(return_value="cleaner text")
        ):
            r = self.client.post(
                "/api/vault-md/ai-snippet", json={"text": "msgy txt", "action": "rewrite"}
            )
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json()["text"], "cleaner text")
        self.assertEqual(r.json()["action"], "rewrite")

    def test_strips_code_fences(self):
        self._endpoint()
        with mock.patch(
            "services.llm.simple_complete", new=mock.AsyncMock(return_value="```\nfenced\n```")
        ):
            r = self.client.post("/api/vault-md/ai-snippet", json={"text": "x", "action": "fix"})
        self.assertEqual(r.json()["text"], "fenced")

    def test_action_picks_the_right_prompt(self):
        self._endpoint()
        seen = {}

        async def fake(msgs, *a, **k):
            seen["sys"] = msgs[0]["content"]
            seen["user"] = msgs[1]["content"]
            return "ok"

        with mock.patch("services.llm.simple_complete", new=fake):
            self.client.post(
                "/api/vault-md/ai-snippet", json={"text": "Helo wrld", "action": "summarize"}
            )
        self.assertIn("Summarize", seen["sys"])
        self.assertEqual(seen["user"], "Helo wrld")

    def test_unknown_action_falls_back_to_rewrite(self):
        self._endpoint()
        seen = {}

        async def fake(msgs, *a, **k):
            seen["sys"] = msgs[0]["content"]
            return "ok"

        with mock.patch("services.llm.simple_complete", new=fake):
            self.client.post("/api/vault-md/ai-snippet", json={"text": "x", "action": "bogus"})
        self.assertIn("Rewrite", seen["sys"])


class DocsAiModelTests(ApiTest):
    """ui-3t — the docs AI model picker (`docs_ai_model` setting) routes doc-AI calls."""

    def _two_endpoints(self):
        d = self.db()
        d.add(ModelEndpoint(name="E1", base_url="http://a", api_key="k", enabled=True, cached_models=json.dumps(["m1"])))
        d.add(ModelEndpoint(name="E2", base_url="http://b", api_key="k", enabled=True, cached_models=json.dumps(["m2", "m3"])))
        d.commit()
        d.close()

    def test_setting_picks_the_endpoint_serving_that_model(self):
        self._two_endpoints()
        seen = {}

        async def fake(msgs, base_url, api_key, model, **k):
            seen["model"] = model
            seen["base"] = base_url
            return "ok"

        with mock.patch("core.settings.load_settings", return_value={"docs_ai_model": "m2"}), \
             mock.patch("services.llm.simple_complete", new=fake):
            self.client.post("/api/vault-md/ai-snippet", json={"text": "x", "action": "rewrite"})
        self.assertEqual(seen["model"], "m2")
        self.assertEqual(seen["base"], "http://b")

    def test_falls_back_to_first_endpoint_without_a_setting(self):
        self._two_endpoints()
        seen = {}

        async def fake(msgs, base_url, api_key, model, **k):
            seen["model"] = model
            return "ok"

        with mock.patch("core.settings.load_settings", return_value={}), \
             mock.patch("services.llm.simple_complete", new=fake):
            self.client.post("/api/vault-md/ai-snippet", json={"text": "x", "action": "rewrite"})
        self.assertEqual(seen["model"], "m1")

    def test_unknown_preferred_model_falls_back(self):
        self._two_endpoints()
        seen = {}

        async def fake(msgs, base_url, api_key, model, **k):
            seen["model"] = model
            return "ok"

        with mock.patch("core.settings.load_settings", return_value={"docs_ai_model": "ghost"}), \
             mock.patch("services.llm.simple_complete", new=fake):
            self.client.post("/api/vault-md/ai-snippet", json={"text": "x", "action": "rewrite"})
        self.assertEqual(seen["model"], "m1")
