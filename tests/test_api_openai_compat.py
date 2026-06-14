import json

from tests._client import ApiTest
from core.database import ModelEndpoint


class OpenAICompatApiTest(ApiTest):
    def test_models_empty(self):
        self.assertEqual(self.client.get("/v1/models").json(), {"object": "list", "data": []})

    def test_models_lists_seeded_endpoint(self):
        d = self.db()
        d.add(ModelEndpoint(name="DeepSeek", base_url="http://x", cached_models=json.dumps(["chat", "coder"])))
        d.commit(); d.close()
        data = self.client.get("/v1/models").json()["data"]
        self.assertEqual({m["id"] for m in data}, {"DeepSeek/chat", "DeepSeek/coder"})

    def test_chat_bad_model_format_400(self):
        r = self.client.post("/v1/chat/completions",
                             json={"model": "noslash", "messages": [{"role": "user", "content": "hi"}]})
        self.assertEqual(r.status_code, 400)

    def test_chat_unknown_endpoint_404(self):
        r = self.client.post("/v1/chat/completions",
                             json={"model": "Nope/m", "messages": [{"role": "user", "content": "hi"}]})
        self.assertEqual(r.status_code, 404)
