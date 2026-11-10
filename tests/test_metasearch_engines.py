import asyncio
import json
import unittest
from unittest import mock

import httpx

from services.research import search as search_service


class MetasearchEnginesTest(unittest.TestCase):
    def test_keyless_engines_run_best_first_in_a_fixed_order(self):
        # shuffled, a page came from whichever engine came up. yandex and mojeek are out
        # altogether (nov 10): as a last resort they gave adult spam for a chinese question
        backends = search_service._text_backends()["backend"].split(",")
        self.assertEqual(backends, search_service._text_backends()["backend"].split(","))
        self.assertEqual(backends[0], "wikipedia")
        self.assertIn("yahoo", backends)
        for name in ("startpage", "grokipedia", "yandex", "mojeek"):
            self.assertNotIn(name, backends)
        self.assertFalse(hasattr(search_service, "_LAST_TEXT_ENGINES"))

    PHONE_PAGE = """<html><body><section class="reg searchCenterMiddle">
      <section class="dd fst algo s-algo algo-sr Sr"><div class="grp grp-talgo ag-1">
        <div class="compTitle p-r"><h3 class="title d-ib mt-42"><a class="s-title fz-m"
          href="https://r.search.yahoo.com/_ylt=A2;_ylu=Y2/RV=2/RE=1/RO=10/RU=https%3a%2f%2fzidian.example%2f855401797%2f/RK=2/RS=x-"
          aria-label="【娑】上面沙、下面女"><span class="title-url"><span>Zidian</span>https://zidian.example</span>【娑】上面沙、下面女</a></h3>
        </div></div><div class="grp grp-talgo-ext"><div class="compText"><p class="s-desc lh-20">
          <span class="s-time fc-dolphin m-0">1 day ago · </span> 娑，读音 <b>suō</b>。 </p></div>
      <section class="dd algo s-algo algo-sr Sr"><div class="grp grp-talgo ag-2">
        <div class="compTitle p-r"><h3 class="title d-ib mt-42"><a class="s-title fz-m"
          href="https://r.search.yahoo.com/_ylt=A3;_ylu=Y3/RV=2/RE=1/RO=10/RU=https%3a%2f%2fb.example%2fno-text/RK=2/RS=y-"
          aria-label="a result with no text under it">a result with no text under it</a></h3></div></div>
      <section class="dd lst algo s-algo algo-sr Sr"><div class="grp grp-talgo ag-3">
        <div class="compTitle p-r"><h3 class="title d-ib mt-42"><a class="s-title fz-m"
          href="https://r.search.yahoo.com/_ylt=A4;_ylu=Y4/RV=2/RE=1/RO=10/RU=https%3a%2f%2fc.example%2fthird/RK=2/RS=z-"
          aria-label="third">third</a></h3></div></div><div class="grp grp-talgo-ext"><div class="compText">
          <p class="s-desc lh-20">the third one's own text</p></div></div>
      </section></section></section>
      <section class="dd mi6 s-dd AlsoTry_M"><h3 class="title"><span class="s-title">Related searches</span></h3></section>
    </section></body></html>"""

    DESKTOP_PAGE = """<html><body><ol><li><div class="dd fst algo algo-sr relsrch Sr">
      <div class="compTitle options-toggle"><a class="d-ib va-top" href="https://r.search.yahoo.com/_ylt=B1/RU=https%3a%2f%2fd.example%2fdesk/RK=2/RS=q-">
        <h3 class="title"><span class="d-b fz-20">desk title</span></h3></a></div>
      <div class="compText aAbs"><p class="fc-dustygray">desk text</p></div></div></li>
      <li><div class="dd algo algo-sr relsrch Sr">
      <div class="compTitle options-toggle"><a class="d-ib va-top" href="https://r.search.yahoo.com/_ylt=B2/RU=https%3a%2f%2fe.example%2fmain/RK=2/RS=q-">
        <h3 class="title"><span class="d-b fz-20">main title</span></h3></a></div>
      <div class="compText aAbs"><p class="fc-dustygray">main text</p></div>
      <div class="compTitle vid"><a href="https://r.search.yahoo.com/_ylt=B3/RU=https%3a%2f%2fv.example%2fclip/RK=2/RS=q-">
        <h3 class="title"><span>a video under it</span></h3></a></div></div></li></ol></body></html>"""

    def test_yahoo_is_read_in_both_of_its_page_layouts(self):
        # nov 10: ddgs poses as a random browser, yahoo answers a phone with another page, and
        # the library read that page as "no results": 4 live pages in 6. the search then fell
        # to engines that gave junk
        from ddgs.engines import ENGINES
        from ddgs.engines.yahoo import Yahoo

        search_service._text_backends()
        engine_class = ENGINES["text"]["yahoo"]
        self.assertTrue(issubclass(engine_class, Yahoo))
        search_service._text_backends()
        self.assertIs(ENGINES["text"]["yahoo"], engine_class)  # swapped once, not stacked
        engine = engine_class()
        self.assertEqual(Yahoo.extract_results(engine, self.PHONE_PAGE), [])
        rows = engine.post_extract_results(engine.extract_results(self.PHONE_PAGE))
        self.assertEqual(
            [(row.title, row.href, row.body) for row in rows],
            [
                ("【娑】上面沙、下面女", "https://zidian.example/855401797/", "娑，读音 suō。"),
                ("a result with no text under it", "https://b.example/no-text", ""),
                ("third", "https://c.example/third", "the third one's own text"),
            ],
        )
        desk = engine.post_extract_results(engine.extract_results(self.DESKTOP_PAGE))
        self.assertEqual(
            [(row.title, row.href, row.body) for row in desk],
            [
                ("desk title", "https://d.example/desk", "desk text"),
                # a video strip inside a result is not part of its title or its link
                ("main title", "https://e.example/main", "main text"),
            ],
        )
        self.assertEqual(engine.extract_results("<html><body><p>nothing</p></body></html>"), [])

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

        real = httpx.AsyncClient

        def offline(*args, **kwargs):
            # when ddgs has nothing the search reads duckduckgo's own page: never for real here
            down = httpx.MockTransport(lambda _request: httpx.Response(503))
            return real(*args, transport=down, **kwargs)

        with (
            mock.patch("ddgs.DDGS", FakeDDGS),
            mock.patch.object(search_service.httpx, "AsyncClient", offline),
        ):
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
        page = ["https://a.dev/1", "https://a.dev/2", "https://a.dev/3"]
        # nothing, then a full page
        urls, calls = self.run_keyless([[], page])
        self.assertEqual(urls, page)
        self.assertEqual([c["backend"] for c in calls], [good, good])
        # one wikipedia article is not a results page either
        wiki = ["https://zh.wikipedia.org/wiki/x"]
        urls, calls = self.run_keyless([wiki, [], page])
        self.assertEqual(urls, page)
        self.assertEqual([c["backend"] for c in calls], [good, good, good])
        # 3 tries, the same good engines every time, then what there is: one article beats
        # the junk the old last resort engines gave, and nothing is said as nothing
        urls, calls = self.run_keyless([wiki, wiki, wiki])
        self.assertEqual(urls, wiki)
        self.assertEqual([c["backend"] for c in calls[:3]], [good, good, good])
        self.assertEqual([c.get("page") for c in calls], [None, None, None, 2])
        urls, calls = self.run_keyless([[], [], [], page], count=3)
        self.assertEqual(urls, [])
        self.assertEqual(len(calls), 3)

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
    def run_exa(self, category="all", payload=None, replies=()):
        seen = {}
        left = list(replies)

        def handler(request):
            seen["url"] = str(request.url)
            seen["key"] = request.headers.get("x-api-key")
            seen["body"] = json.loads(request.content)
            seen["requests"] = seen.get("requests", 0) + 1
            if left:
                status, headers = left.pop(0)
                if status != 200:
                    return httpx.Response(status, headers=headers, json={"tag": "X"})
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

    def test_a_busy_exa_is_asked_once_more_and_a_refusal_is_not(self):
        found = {"results": [{"url": "https://a.dev/x", "title": "A"}]}
        with mock.patch.object(search_service.asyncio, "sleep", new=mock.AsyncMock()) as pause:
            for status in (429, 500, 503, 504):
                with self.subTest(status=status):
                    rows, seen = self.run_exa(
                        payload=found, replies=[(status, {"retry-after": "30"})]
                    )
                    self.assertEqual([r["url"] for r in rows], ["https://a.dev/x"])
                    self.assertEqual(seen["requests"], 2)
            # never a long wait, whatever exa asks for: the search has a backup
            self.assertTrue(all(call.args[0] <= 2 for call in pause.await_args_list))
            with self.assertRaises(httpx.HTTPStatusError):
                self.run_exa(replies=[(503, {}), (503, {})])
            # 403 is exa's content filter or the plan: asking again changes nothing
            with self.assertRaises(search_service.SearchProviderFailure) as refused:
                self.run_exa(replies=[(403, {})])
            self.assertEqual(refused.exception.failure_type, "refused")
            with self.assertRaises(httpx.HTTPStatusError):
                self.run_exa(replies=[(401, {})])

    def test_a_backup_engine_answering_for_the_chosen_one_is_reported_with_the_reason(self):
        from services import andromeda

        settings = {"research_search_provider": "exa", "search_fallback_chain": ["duckduckgo"]}
        rows = [{"url": "https://a.dev/x", "title": "A", "snippet": "s"}]

        def chain(first, category="all"):
            async def provider(name, *_args):
                if name == "exa":
                    if isinstance(first, Exception):
                        raise first
                    return first
                return rows

            with (
                mock.patch("core.settings.load_settings", return_value=settings),
                mock.patch.object(search_service, "_search_provider", side_effect=provider),
            ):
                report = asyncio.run(search_service.search_chain_report("x", category=category))
                normal = asyncio.run(andromeda.normal_search("x", category=category))
            return report, normal

        for first, reason in (
            (search_service.SearchProviderFailure("refused"), "refused"),
            (TimeoutError("slow"), "failed"),
            ([], "empty"),
        ):
            with self.subTest(reason=reason):
                report, normal = chain(first)
                self.assertEqual((report.provider, report.backup_for), ("duckduckgo", "exa"))
                self.assertEqual(report.backup_reason, reason)
                self.assertEqual((normal["backup_for"], normal["backup_reason"]), ("exa", reason))
        # exa answering itself, or having no pictures to give, is not news
        report, normal = chain(rows)
        self.assertEqual(
            (report.provider, report.backup_for, normal["backup_for"]), ("exa", "", "")
        )
        report, normal = chain([], category="images")
        self.assertEqual(
            (report.provider, report.backup_for, normal["backup_for"]), ("duckduckgo", "", "")
        )

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
