import unittest
from types import SimpleNamespace

from services.model_providers import CatalogFetchError, adapter_name, fetch_catalog


class Response:
    def __init__(self, payload, status=200):
        self.payload = payload
        self.status_code = status

    def json(self):
        if isinstance(self.payload, Exception):
            raise self.payload
        return self.payload


class Client:
    def __init__(self, response):
        self.response = response
        self.calls = []

    async def get(self, url, headers=None):
        self.calls.append((url, headers or {}))
        return self.response


def endpoint(url, *, key="key", adapter="auto"):
    return SimpleNamespace(base_url=url, api_key=key, provider_adapter=adapter)


class ModelProviderAdapterTest(unittest.IsolatedAsyncioTestCase):
    async def test_openai_compatible_catalog_uses_header_and_live_ids(self):
        client = Client(
            Response(
                {
                    "data": [
                        {"id": "chat-a", "created": 10, "owned_by": "provider"},
                        {"id": "chat-a"},
                        {"id": "gpt-image-1"},
                    ]
                }
            )
        )
        result = await fetch_catalog(endpoint("https://api.example.test/v1"), client=client)
        self.assertEqual(result.model_ids, ["chat-a", "gpt-image-1"])
        self.assertEqual(client.calls[0][0], "https://api.example.test/v1/models")
        self.assertEqual(client.calls[0][1]["authorization"], "Bearer key")
        self.assertNotIn("key", client.calls[0][0])

    async def test_anthropic_adapter_uses_anthropic_headers(self):
        client = Client(Response({"data": [{"id": "claude-live", "display_name": "Claude"}]}))
        result = await fetch_catalog(endpoint("https://api.anthropic.com"), client=client)
        self.assertEqual(result.adapter, "anthropic")
        self.assertEqual(client.calls[0][0], "https://api.anthropic.com/v1/models?limit=100")
        self.assertEqual(client.calls[0][1]["x-api-key"], "key")

    async def test_ollama_adapter_uses_tags_without_credentials(self):
        client = Client(Response({"models": [{"name": "qwen:7b", "size": 7}]}))
        result = await fetch_catalog(endpoint("http://localhost:11434/v1"), client=client)
        self.assertEqual(result.model_ids, ["qwen:7b"])
        self.assertEqual(client.calls[0], ("http://localhost:11434/api/tags", {}))

    async def test_gemini_adapter_filters_non_generation_models(self):
        client = Client(
            Response(
                {
                    "models": [
                        {
                            "name": "models/gemini-live",
                            "supportedGenerationMethods": ["generateContent"],
                        },
                        {"name": "models/embed", "supportedGenerationMethods": ["embedContent"]},
                    ]
                }
            )
        )
        result = await fetch_catalog(
            endpoint("https://generativelanguage.googleapis.com"), client=client
        )
        self.assertEqual(result.model_ids, ["gemini-live"])
        self.assertEqual(client.calls[0][1]["x-goog-api-key"], "key")

    async def test_auth_failure_has_stable_code_and_no_response_body(self):
        client = Client(Response({"error": "private provider response"}, status=401))
        with self.assertRaises(CatalogFetchError) as raised:
            await fetch_catalog(endpoint("https://api.example.test"), client=client)
        self.assertEqual(raised.exception.code, "authentication_failed")
        self.assertNotIn("private", str(raised.exception))

    async def test_manual_adapter_never_calls_network(self):
        client = Client(Response({}))
        with self.assertRaisesRegex(CatalogFetchError, "discovery_unsupported"):
            await fetch_catalog(endpoint("https://custom.example", adapter="manual"), client=client)
        self.assertEqual(client.calls, [])

    def test_gemini_openai_compat_url_uses_compat_adapter(self):
        ep = endpoint("https://generativelanguage.googleapis.com/v1beta/openai")
        self.assertEqual(adapter_name(ep), "openai-compatible")


if __name__ == "__main__":
    unittest.main()
