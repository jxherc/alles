import json

from core.database import ModelEndpoint
from tests._client import ApiTest


class OpenAICompatApiTest(ApiTest):
    def test_models_empty(self):
        self.assertEqual(self.client.get("/v1/models").json(), {"object": "list", "data": []})

    def test_models_lists_seeded_endpoint(self):
        d = self.db()
        d.add(
            ModelEndpoint(
                name="DeepSeek", base_url="http://x", cached_models=json.dumps(["chat", "coder"])
            )
        )
        d.commit()
        d.close()
        data = self.client.get("/v1/models").json()["data"]
        self.assertEqual({m["id"] for m in data}, {"DeepSeek/chat", "DeepSeek/coder"})

    def test_chat_bad_model_format_400(self):
        r = self.client.post(
            "/v1/chat/completions",
            json={"model": "noslash", "messages": [{"role": "user", "content": "hi"}]},
        )
        self.assertEqual(r.status_code, 400)

    def test_chat_unknown_endpoint_404(self):
        r = self.client.post(
            "/v1/chat/completions",
            json={"model": "Nope/m", "messages": [{"role": "user", "content": "hi"}]},
        )
        self.assertEqual(r.status_code, 404)

    def test_models_disabled_not_listed(self):
        d = self.db()
        d.add(
            ModelEndpoint(
                name="Hidden", base_url="http://h", cached_models=json.dumps(["x"]), enabled=False
            )
        )
        d.commit()
        d.close()
        data = self.client.get("/v1/models").json()["data"]
        self.assertEqual(data, [])

    def test_models_empty_cached_models(self):
        d = self.db()
        d.add(ModelEndpoint(name="Empty", base_url="http://e", cached_models="[]"))
        d.commit()
        d.close()
        data = self.client.get("/v1/models").json()["data"]
        self.assertEqual(data, [])

    def test_models_owned_by_lowercase(self):
        d = self.db()
        d.add(
            ModelEndpoint(
                name="MyProvider", base_url="http://p", cached_models=json.dumps(["gpt4"])
            )
        )
        d.commit()
        d.close()
        data = self.client.get("/v1/models").json()["data"]
        self.assertEqual(len(data), 1)
        self.assertEqual(data[0]["owned_by"], "myprovider")
        self.assertEqual(data[0]["created"], 0)
        self.assertEqual(data[0]["object"], "model")

    def test_models_top_level_object_field(self):
        resp = self.client.get("/v1/models").json()
        self.assertEqual(resp["object"], "list")
        self.assertIn("data", resp)

    def test_models_multiple_endpoints(self):
        d = self.db()
        d.add(ModelEndpoint(name="Ep1", base_url="http://a", cached_models=json.dumps(["m1"])))
        d.add(
            ModelEndpoint(name="Ep2", base_url="http://b", cached_models=json.dumps(["m2", "m3"]))
        )
        d.commit()
        d.close()
        data = self.client.get("/v1/models").json()["data"]
        ids = {m["id"] for m in data}
        self.assertEqual(ids, {"Ep1/m1", "Ep2/m2", "Ep2/m3"})

    def test_chat_disabled_endpoint_404(self):
        d = self.db()
        d.add(
            ModelEndpoint(
                name="Disabled", base_url="http://d", cached_models=json.dumps(["m"]), enabled=False
            )
        )
        d.commit()
        d.close()
        r = self.client.post(
            "/v1/chat/completions",
            json={"model": "Disabled/m", "messages": [{"role": "user", "content": "hi"}]},
        )
        self.assertEqual(r.status_code, 404)

    def test_models_only_enabled_shown(self):
        d = self.db()
        d.add(
            ModelEndpoint(
                name="On", base_url="http://on", cached_models=json.dumps(["yes"]), enabled=True
            )
        )
        d.add(
            ModelEndpoint(
                name="Off", base_url="http://off", cached_models=json.dumps(["no"]), enabled=False
            )
        )
        d.commit()
        d.close()
        data = self.client.get("/v1/models").json()["data"]
        ids = {m["id"] for m in data}
        self.assertIn("On/yes", ids)
        self.assertNotIn("Off/no", ids)
