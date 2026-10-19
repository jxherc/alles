import asyncio
import json
import unittest
from unittest import mock

import httpx

from services.research import search as search_service


class MetasearchEnginesTest(unittest.TestCase):
    def test_keyless_metasearch_skips_engines_that_only_return_captchas(self):
        backends = search_service._text_backends()["backend"].split(",")
        self.assertNotIn("startpage", backends)
        self.assertIn("duckduckgo", backends)
        self.assertEqual(backends[0], "wikipedia")

    def test_startpage_is_not_a_search_engine_option(self):
        self.assertNotIn("startpage", search_service._KNOWN_PROVIDERS)


class ExaEngineTest(unittest.TestCase):
    def run_exa(self, category="all", payload=None):
        seen = {}

        def handler(request):
            seen["url"] = str(request.url)
            seen["key"] = request.headers.get("x-api-key")
            seen["body"] = json.loads(request.content)
            return httpx.Response(200, json=payload or {"results": []})

        real = httpx.AsyncClient

        def client(*args, **kwargs):
            return real(*args, transport=httpx.MockTransport(handler), **kwargs)

        with mock.patch.object(search_service.httpx, "AsyncClient", client):
            rows = asyncio.run(search_service._search_exa("wireguard", "k-1", 8, category))
        return rows, seen

    def test_asks_for_the_instant_mode_with_short_snippets(self):
        rows, seen = self.run_exa(
            payload={
                "results": [
                    {"url": "https://a.dev/x", "title": "A", "highlights": ["one", "two"]},
                    {"title": "no url"},
                    {"url": "https://b.dev", "title": None, "publishedDate": "2026-10-01"},
                ]
            }
        )
        self.assertEqual(seen["url"], "https://api.exa.ai/search")
        self.assertEqual(seen["key"], "k-1")
        self.assertEqual(seen["body"]["type"], "instant")
        self.assertEqual(seen["body"]["numResults"], 8)
        self.assertIn("highlights", seen["body"]["contents"])
        self.assertNotIn("category", seen["body"])
        self.assertEqual([r["url"] for r in rows], ["https://a.dev/x", "https://b.dev"])
        self.assertEqual(rows[0]["snippet"], "one two")
        self.assertEqual(rows[1]["published"], "2026-10-01")

    def test_news_uses_the_news_category(self):
        _rows, seen = self.run_exa("news")
        self.assertEqual(seen["body"]["category"], "news")

    def test_images_and_videos_fall_through_to_the_next_engine(self):
        for category in ("images", "videos"):
            rows, seen = self.run_exa(category)
            self.assertEqual(rows, [])
            self.assertEqual(seen, {})

    def test_missing_key_is_a_configuration_failure(self):
        with mock.patch.dict("os.environ", {"EXA_API_KEY": ""}):
            with self.assertRaises(search_service.SearchProviderFailure):
                asyncio.run(search_service._search_provider("exa", "q", {}, 8))


class KeyedEnginesTest(unittest.TestCase):
    # request shape and result paths from each provider's docs (checked 2026-10-18)
    CASES = {
        "deepseek": (
            "https://api.deepseek.com/v1/tools/search",
            ("authorization", "Bearer k"),
            {"query": "q", "count": 8},
            {
                "results": [
                    {"url": "https://a.dev", "title": "A", "snippet": "s", "date": "2026-10-01"}
                ]
            },
        ),
        "firecrawl": (
            "https://api.firecrawl.dev/v2/search",
            ("authorization", "Bearer k"),
            {"query": "q", "limit": 8},
            {"data": {"web": [{"url": "https://a.dev", "title": "A", "description": "s"}]}},
        ),
        "you": (
            "https://ydc-index.io/v1/search",
            ("x-api-key", "k"),
            {"query": "q", "count": 8},
            {"results": {"web": [{"url": "https://a.dev", "title": "A", "description": "s"}]}},
        ),
        "linkup": (
            "https://api.linkup.so/v1/search",
            ("authorization", "Bearer k"),
            {"q": "q", "depth": "fast", "outputType": "searchResults", "maxResults": 8},
            {
                "results": [
                    {"type": "text", "name": "A", "url": "https://a.dev", "content": "s"},
                    {"type": "image", "name": "pic", "url": "https://a.dev/i.png"},
                ]
            },
        ),
        "perplexity": (
            "https://api.perplexity.ai/search",
            ("authorization", "Bearer k"),
            {"query": "q", "max_results": 8, "search_type": "fast"},
            {"results": [{"url": "https://a.dev", "title": "A", "snippet": "s"}]},
        ),
    }

    def run_engine(self, name, payload):
        seen = {}

        def handler(request):
            seen["url"] = str(request.url).split("?")[0]
            seen["headers"] = request.headers
            seen["body"] = json.loads(request.content) if request.content else None
            return httpx.Response(200, json=payload)

        real = httpx.AsyncClient

        def client(*args, **kwargs):
            return real(*args, transport=httpx.MockTransport(handler), **kwargs)

        settings = {search_service.BY_ID[name].key: "k"}
        with mock.patch.object(search_service.httpx, "AsyncClient", client):
            rows = asyncio.run(search_service._search_provider(name, "q", settings, 8))
        return rows, seen

    def test_each_engine_sends_its_documented_request(self):
        for name, (url, (header, value), body, payload) in self.CASES.items():
            with self.subTest(engine=name):
                rows, seen = self.run_engine(name, payload)
                self.assertEqual(seen["url"], url)
                self.assertEqual(seen["headers"][header], value)
                self.assertEqual(seen["body"], body)
                self.assertEqual(rows[0]["url"], "https://a.dev")
                self.assertEqual((rows[0]["title"], rows[0]["snippet"]), ("A", "s"))
                self.assertEqual(len(rows), 1)

    def test_jina_reads_a_bare_list_or_one_under_data(self):
        for payload in (
            [{"url": "https://a.dev", "title": "A", "description": "s"}],
            {"data": [{"url": "https://a.dev", "title": "A", "description": "s"}]},
        ):
            rows, seen = self.run_engine("jina", payload)
            self.assertEqual(seen["url"], "https://s.jina.ai/")
            self.assertEqual(seen["headers"]["authorization"], "Bearer k")
            self.assertEqual(seen["headers"]["x-respond-with"], "no-content")
            self.assertEqual(rows[0]["snippet"], "s")

    def test_deepseek_keeps_the_query_inside_its_limit(self):
        _rows, seen = self.run_engine("deepseek", {"results": []})
        self.assertLessEqual(len(seen["body"]["query"]), 128)

    def test_missing_keys_are_configuration_failures(self):
        for name in self.CASES:
            with self.subTest(engine=name), self.assertRaises(search_service.SearchProviderFailure):
                asyncio.run(search_service._search_provider(name, "q", {}, 8))


if __name__ == "__main__":
    unittest.main()
