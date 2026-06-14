from tests._client import ApiTest


class ImagesApiTest(ApiTest):
    def test_empty_prompt_400(self):
        self.assertEqual(self.client.post("/api/images/generate", json={"prompt": "  "}).status_code, 400)

    def test_no_endpoint_400(self):
        # fresh db has no model endpoint → clean error, not a crash
        r = self.client.post("/api/images/generate", json={"prompt": "a red bicycle"})
        self.assertEqual(r.status_code, 400)
        self.assertIn("endpoint", r.json()["detail"].lower())
