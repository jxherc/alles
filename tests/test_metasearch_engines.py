import asyncio
import json
import unittest
from unittest import mock

import httpx

from services.research import search as search_service


class MetasearchEnginesTest(unittest.TestCase):
    def test_keyless_engines_run_best_first_in_a_fixed_order(self):
        # shuffled, a page came from whichever engine came up; the weak ones are a last resort now
        backends = search_service._text_backends()["backend"].split(",")
        last = search_service._text_backends(search_service._LAST_TEXT_ENGINES)["backend"]
        self.assertEqual(backends, search_service._text_backends()["backend"].split(","))
        self.assertEqual(backends[0], "wikipedia")
        self.assertIn("yahoo", backends)
        for name in ("startpage", "grokipedia", "yandex", "mojeek"):
            self.assertNotIn(name, backends)
        for name in ("startpage", "grokipedia", "wikipedia", "yahoo"):
            self.assertNotIn(name, last.split(","))

    def test_a_query_in_another_script_is_searched_in_its_own_region(self):
        for query, region in (
            ("苹果", "cn-zh"),
            ("りんご 品種", "jp-ja"),
            ("東京の天気は", "jp-ja"),
            ("사과", "kr-ko"),
            ("яблоко", "ru-ru"),
            ("تفاح", "xa-ar"),
            ("apple", "us-en"),
            ("café près de moi", "us-en"),
            ("", "us-en"),
        ):
            with self.subTest(query=query):
                self.assertEqual(search_service.search_region(query), region)

    def run_keyless(self, replies, category="all", query="苹果", count=3):
        """_search_duckduckgo over a fake ddgs whose text() gives `replies` in turn."""
        calls = []

        class FakeDDGS:
            def __enter__(self):
                return self

            def __exit__(self, *_exc):
                return False

            def text(self, _query, **kwargs):
                calls.append(kwargs)
                reply = replies[len(calls) - 1] if len(calls) <= len(replies) else []
                if not reply:
                    raise RuntimeError("No results found.")
                return [{"href": url, "title": url, "body": "b"} for url in reply]

            def images(self, _query, **kwargs):
                calls.append(kwargs)
                return [{"url": "https://a.dev/p", "image": "https://a.dev/i.png"}]

        with mock.patch("ddgs.DDGS", FakeDDGS):
            rows = asyncio.run(search_service._search_duckduckgo(query, count, category))
        return [row["url"] for row in rows], calls

    def test_the_keyless_search_sends_the_region_and_the_engine_order(self):
        good = search_service._text_backends()["backend"]
        urls, calls = self.run_keyless([["https://a.cn/1", "https://a.cn/2", "https://a.cn/3"]])
        self.assertEqual(urls, ["https://a.cn/1", "https://a.cn/2", "https://a.cn/3"])
        self.assertEqual([(c["region"], c["backend"]) for c in calls], [("cn-zh", good)])
        _urls, calls = self.run_keyless([], category="images")
        self.assertEqual(calls[0]["region"], "cn-zh")

    def test_an_empty_reply_from_the_good_engines_is_asked_once_more(self):
        good = search_service._text_backends()["backend"]
        last = search_service._text_backends(search_service._LAST_TEXT_ENGINES)["backend"]
        page = ["https://a.dev/1", "https://a.dev/2", "https://a.dev/3"]
        # nothing, then a full page: the last resort engines are never asked
        urls, calls = self.run_keyless([[], page])
        self.assertEqual(urls, page)
        self.assertEqual([c["backend"] for c in calls], [good, good])
        # one wikipedia article is not a results page either
        wiki = ["https://zh.wikipedia.org/wiki/x"]
        urls, calls = self.run_keyless([wiki, wiki, page])
        self.assertEqual(urls, page)
        self.assertEqual([c["backend"] for c in calls], [good, good, last])

    def test_a_short_first_page_is_filled_from_the_second(self):
        urls, calls = self.run_keyless(
            [["https://a.dev/1", "https://a.dev/2"], ["https://a.dev/2", "https://a.dev/3"]]
        )
        self.assertEqual(urls, ["https://a.dev/1", "https://a.dev/2", "https://a.dev/3"])
        self.assertEqual(calls[1]["page"], 2)
        self.assertEqual(calls[1]["backend"], calls[0]["backend"])

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

    def test_asks_for_the_default_mode_with_short_snippets(self):
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
        # "instant" is a legacy mode that trades depth for speed (exa's search reference)
        self.assertEqual(seen["body"]["type"], "auto")
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

    def test_exa_snippets_lose_their_markdown(self):
        plain = search_service._plain_snippet(
            "## noun ser·en·dip·i·ty **luck** see [Wiktionary](https://w.example/x) - one"
        )
        self.assertEqual(plain, "noun ser·en·dip·i·ty luck see Wiktionary one")


if __name__ == "__main__":
    unittest.main()
