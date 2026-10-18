import asyncio
from unittest import mock
from urllib.parse import parse_qs, urlsplit

from core.settings import load_settings, save_settings
from services.research import search as search_service
from tests._client import ApiTest


class StartpageEngineTest(ApiTest):
    def test_startpage_is_never_fetched_and_the_chain_behind_it_answers(self):
        calls = []

        async def provider(name, *_args):
            calls.append(name)
            return [{"url": "https://example.com", "title": "hit", "snippet": "s"}]

        settings = {"search_provider": "startpage", "search_fallback_chain": ["duckduckgo"]}
        with (
            mock.patch("core.settings.load_settings", return_value=settings),
            mock.patch.object(search_service, "_search_provider", side_effect=provider),
        ):
            report = asyncio.run(search_service.search_chain_report("fastapi"))
            exact = asyncio.run(search_service.search_chain_report("fastapi", override="startpage"))

        self.assertNotIn("startpage", calls)
        self.assertEqual(report.provider, "duckduckgo")
        self.assertEqual(exact.provider, "duckduckgo")

    def test_url_keeps_the_query_and_category(self):
        url = search_service.startpage_url("a & b?", "news")
        parts = urlsplit(url)
        self.assertEqual(
            (parts.scheme, parts.netloc, parts.path), ("https", "www.startpage.com", "/sp/search")
        )
        self.assertEqual(parse_qs(parts.query), {"query": ["a & b?"], "cat": ["news"]})

    def test_search_returns_a_startpage_link_when_it_is_the_engine(self):
        settings = load_settings()
        settings.update(search_provider="startpage", andromeda_overview=False)
        save_settings(settings)

        async def fake_normal(query, **_kwargs):
            return {"status": "ready", "results": [{"url": "https://example.com", "title": "t"}]}

        with (
            mock.patch.dict("os.environ", {"ALLES_AFTERLIFE_FEATURES": "afterlife_andromeda"}),
            mock.patch("routes.andromeda._require_flag", return_value=None),
            mock.patch("services.andromeda.normal_search", side_effect=fake_normal),
        ):
            body = self.client.post("/api/andromeda/search", json={"query": "python"}).json()
            other = self.client.post(
                "/api/andromeda/search", json={"query": "python", "provider": "duckduckgo"}
            ).json()

        self.assertEqual(body["results_link"]["engine"], "startpage")
        self.assertIn("query=python", body["results_link"]["url"])
        self.assertIsNone(other["results_link"])
