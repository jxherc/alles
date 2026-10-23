import json
from unittest import mock

from core import settings as settings_module
from core.settings import load_settings, save_settings
from services.research import engines
from tests._client import ApiTest


def _raw():
    return json.loads(settings_module._SETTINGS_FILE.read_text())


class SearchEnginesApiTest(ApiTest):
    def setUp(self):
        super().setUp()
        save_settings(
            {
                "custom_search_engines": [],
                "custom_search_keys": {},
                "deepseek_search_api_key": "",
                "search_provider": "duckduckgo",
                "search_fallback": "duckduckgo",
                "search_fallback_chain": ["duckduckgo"],
            }
        )

    def test_list_names_every_builtin_engine_and_never_a_key(self):
        rows = self.client.get("/api/search/engines").json()["engines"]
        ids = [row["id"] for row in rows]
        self.assertEqual(ids[0], "duckduckgo")
        for engine_id in ("exa", "deepseek", "brave", "serper", "firecrawl", "you", "perplexity"):
            self.assertIn(engine_id, ids)
        self.assertNotIn("startpage", ids)
        save_settings({"exa_api_key": "secret-exa-value"})
        listed = json.dumps(self.client.get("/api/search/engines").json())
        self.assertNotIn("secret-exa-value", listed)

    def test_engine_keys_are_secret_and_sealed_on_disk(self):
        r = self.client.patch("/api/settings", json={"search_keys": {"deepseek": " dk-1 "}})
        self.assertEqual(r.status_code, 200)
        public = self.client.get("/api/settings").json()
        self.assertNotIn("deepseek_search_api_key", public)
        self.assertTrue(public["deepseek_search_api_key_configured"])
        self.assertTrue(_raw()["deepseek_search_api_key"].startswith("enc2:"))
        self.assertEqual(load_settings()["deepseek_search_api_key"], "dk-1")
        row = next(
            e
            for e in self.client.get("/api/search/engines").json()["engines"]
            if e["id"] == "deepseek"
        )
        self.assertTrue(row["configured"])

    def test_a_key_for_an_engine_without_keys_is_refused(self):
        for engine_id in ("duckduckgo", "nope"):
            r = self.client.patch("/api/settings", json={"search_keys": {engine_id: "x"}})
            self.assertEqual(r.status_code, 400)

    def test_custom_engine_round_trip_keeps_its_key_sealed(self):
        body = {
            "name": "my index",
            "url": "https://search.example.com/api?q={query}&n={count}",
            "key_header": "Authorization",
            "key_prefix": "Bearer ",
            "key": "ck-1",
            "results": "data.items",
        }
        made = self.client.post("/api/search/custom", json=body).json()
        engine_id = made["id"]
        self.assertTrue(engine_id.startswith("custom-"))
        self.assertTrue(made["key_configured"])
        self.assertNotIn("ck-1", json.dumps(self.client.get("/api/settings").json()))
        self.assertTrue(_raw()["custom_search_keys"][engine_id].startswith("enc2:"))
        self.assertEqual(load_settings()["custom_search_keys"][engine_id], "ck-1")

        # an edit without a key keeps the saved one
        edited = self.client.put(
            f"/api/search/custom/{engine_id}", json={**body, "name": "renamed", "key": None}
        ).json()
        self.assertEqual(edited["label"], "renamed")
        self.assertEqual(load_settings()["custom_search_keys"][engine_id], "ck-1")

        self.client.patch("/api/settings", json={"search_provider": engine_id})
        self.assertEqual(self.client.delete(f"/api/search/custom/{engine_id}").status_code, 200)
        left = load_settings()
        self.assertEqual(left["search_provider"], "duckduckgo")
        self.assertNotIn(engine_id, left["custom_search_keys"])
        self.assertEqual(self.client.delete(f"/api/search/custom/{engine_id}").status_code, 404)

    def test_custom_engine_form_rules(self):
        bad = [
            {"name": "", "url": "https://a.dev/?q={query}"},
            {"name": "x", "url": "https://a.dev/search"},
            {"name": "x", "url": "http://10.0.0.5/?q={query}"},
            {"name": "x", "url": "https://a.dev/?q={query}", "method": "PUT"},
            {"name": "x", "url": "https://a.dev/?q={query}", "key_header": "bad header"},
            {"name": "x", "url": "https://a.dev/?q={query}", "results": "a..b"},
        ]
        for body in bad:
            with self.subTest(body=body):
                self.assertEqual(self.client.post("/api/search/custom", json=body).status_code, 400)
        ok = self.client.post(
            "/api/search/custom", json={"name": "local", "url": "http://127.0.0.1:8888/?q={query}"}
        )
        self.assertEqual(ok.status_code, 200)

    def test_unknown_engine_is_refused_by_search_and_test(self):
        self.assertEqual(
            self.client.post("/api/search/test", json={"engine": "nope"}).status_code, 404
        )

    def test_test_reports_count_and_time(self):
        async def fake(name, query, settings, count, category="all"):
            return [{"url": "https://a.dev", "title": "first hit"}]

        with mock.patch("services.research.search._search_provider", side_effect=fake):
            r = self.client.post("/api/search/test", json={"engine": "duckduckgo"}).json()
        self.assertTrue(r["ok"])
        self.assertEqual((r["count"], r["first"]), (1, "first hit"))
        self.assertIn("ms", r)


class CustomEngineRequestTest(ApiTest):
    def test_query_is_escaped_for_the_address_and_the_json_body(self):
        row = engines.clean_custom(
            {
                "name": "x",
                "url": "https://a.dev/search?n={count}",
                "method": "POST",
                "body": '{"q": "{query}", "n": {count}}',
                "key_header": "X-Key",
                "key_prefix": "",
            }
        )
        method, url, headers, body = engines.custom_request(row, "k", 'say "hi" & go', 7)
        self.assertEqual((method, url), ("POST", "https://a.dev/search?n=7"))
        self.assertEqual(json.loads(body), {"q": 'say "hi" & go', "n": 7})
        self.assertEqual(headers["X-Key"], "k")
        get_row = engines.clean_custom({"name": "g", "url": "https://a.dev/?q={query}"})
        _m, url, headers, body = engines.custom_request(get_row, "", "a b&c", 8)
        self.assertEqual(url, "https://a.dev/?q=a+b%26c")
        self.assertEqual(body, "")

    def test_results_follow_the_configured_paths(self):
        row = {
            "results": "data.items",
            "url_field": "link",
            "title_field": "meta.name",
            "snippet_field": "text",
        }
        data = {
            "data": {
                "items": [
                    {"link": "https://a.dev", "meta": {"name": "A"}, "text": "s"},
                    {"link": "javascript:alert(1)", "meta": {"name": "bad"}},
                    {"link": "https://b.dev"},
                ]
            }
        }
        rows = engines.custom_results(row, data, 5)
        self.assertEqual([r["url"] for r in rows], ["https://a.dev", "https://b.dev"])
        self.assertEqual((rows[0]["title"], rows[0]["snippet"]), ("A", "s"))
        self.assertEqual(rows[1]["title"], "https://b.dev")
