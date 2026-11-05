import os
import sys
from unittest import mock

from core.database import ModelEndpoint
from core.settings import save_settings
from services import andromeda, andromeda_spelling
from services.research import search as research_search
from tests._client import ApiTest


class SpellingFixTest(ApiTest):
    def test_a_swapped_pair_is_fixed(self):
        self.assertEqual(andromeda_spelling.correct("achievemenst"), "achievements")

    def test_only_the_misspelled_word_changes(self):
        self.assertEqual(
            andromeda_spelling.correct("how many achievemenst in minecraft"),
            "how many achievements in minecraft",
        )
        self.assertEqual(andromeda_spelling.correct("Achievemenst  list"), "Achievements  list")
        self.assertEqual(andromeda_spelling.correct("achievemenst?"), "achievements?")

    def test_common_misspellings(self):
        for typed, fixed in (
            ("recieve", "receive"),
            ("definately", "definitely"),
            ("adress", "address"),
            ("goverment", "government"),
            ("untill", "until"),
        ):
            with self.subTest(typed=typed):
                self.assertEqual(andromeda_spelling.correct(typed), fixed)

    def test_words_the_list_knows_stay(self):
        for query in ("achievements in minecraft", "weather in toronto", "how to tie a tie"):
            with self.subTest(query=query):
                self.assertIsNone(andromeda_spelling.correct(query))

    def test_names_and_brands_stay(self):
        for query in (
            "tft",
            "exa",
            "alles",
            "jxherc",
            "gmail",
            "xbox",
            "spacex",
            "wifi",
            "numpy",
            "kpop",
            "figma",
            "pokemon",
            "macos",
            "tft patch notes",
            "alles andromeda",
        ):
            with self.subTest(query=query):
                self.assertIsNone(andromeda_spelling.correct(query))

    def test_a_clear_winner_is_needed(self):
        # college and colleague are both one edit from "collegue"
        self.assertIsNone(andromeda_spelling.correct("collegue"))
        # a word from another language doesn't get an english look-alike
        self.assertIsNone(andromeda_spelling.correct("pelicula favorita"))
        self.assertIsNone(andromeda_spelling.correct("película favorita"))

    def test_what_is_not_plain_text_stays(self):
        for query in (
            "ACHIEVEMENST",
            "achievemenst2",
            "iPhone achievemenst2",
            '"achievemenst" meaning',
            '"achievemenst meaning',
            "https://achievemenst.com/x",
            "achievemenst.com",
            "-achievemenst",
            "foo !w achievemenst",
            "intitle:achievemenst",
            "",
            "   ",
        ):
            with self.subTest(query=query):
                self.assertIsNone(andromeda_spelling.correct(query))

    def test_operators_and_bangs_are_kept_as_typed(self):
        self.assertEqual(
            andromeda_spelling.correct("achievemenst site:github.com"),
            "achievements site:github.com",
        )
        self.assertEqual(
            andromeda_spelling.correct('"exact phrase" achievemenst'),
            '"exact phrase" achievements',
        )
        self.assertEqual(
            andromeda_spelling.correct("achievemenst !w achievemenst"),
            "achievements !w achievemenst",
        )

    def test_a_pile_of_unknown_words_is_not_fixed(self):
        self.assertIsNone(andromeda_spelling.correct("achievemenst recieve adress untill"))

    def test_a_missing_package_means_no_fix(self):
        andromeda_spelling._checker.cache_clear()
        try:
            with mock.patch.dict(sys.modules, {"spellchecker": None}):
                self.assertIsNone(andromeda_spelling.correct("achievemenst"))
        finally:
            andromeda_spelling._checker.cache_clear()
        self.assertEqual(andromeda_spelling.correct("achievemenst"), "achievements")

    def test_an_engine_fix_is_checked(self):
        fix = andromeda_spelling.from_engine
        self.assertEqual(fix("achievemenst", "achievements"), "achievements")
        self.assertEqual(fix("tft patchs", " tft  patches "), "tft patches")
        self.assertIsNone(fix("achievemenst", "achievemenst"))
        self.assertIsNone(fix("achievemenst", "Achievemenst"))
        self.assertIsNone(fix("achievemenst", "something completely different"))
        self.assertIsNone(fix("achievemenst", ""))
        self.assertIsNone(fix("achievemenst", None))
        self.assertIsNone(fix('"achievemenst"', "achievements"))
        self.assertIsNone(fix("achievemenst site:a.dev", "achievements site:a.dev"))
        self.assertIsNone(fix("!w achievemenst", "achievements"))


class SearchRouteTest(ApiTest):
    def setUp(self):
        self.flags = mock.patch.dict(
            os.environ, {"ALLES_AFTERLIFE_FEATURES": "afterlife_shell,afterlife_andromeda"}
        )
        self.flags.start()
        super().setUp()
        save_settings({"andromeda_normal_results": True, "andromeda_overview": True})
        andromeda_spelling._checker.cache_clear()
        self.seen = []

    def tearDown(self):
        super().tearDown()
        self.flags.stop()

    def _search_with(self, *replies):
        """normal_search standing in for the engines. each reply is merged into a ready result."""
        queue = list(replies)

        async def fake(query, **_kwargs):
            self.seen.append(query)
            extra = queue.pop(0) if queue else {}
            return {
                "status": "ready",
                "results": [{"url": "https://example.com/a", "title": "a", "snippet": "b"}],
                "provider": "fake",
                "elapsed_ms": 1,
                "error": "",
                **extra,
            }

        return mock.patch.object(andromeda, "normal_search", side_effect=fake)

    def _post(self, query, **extra):
        return self.client.post("/api/andromeda/search", json={"query": query, **extra})

    def test_the_search_runs_on_the_fixed_query_and_says_so(self):
        with self._search_with():
            body = self._post("how many achievemenst in minecraft").json()
        self.assertEqual(self.seen, ["how many achievements in minecraft"])
        self.assertEqual(body["query"], "how many achievements in minecraft")
        self.assertEqual(body["corrected_from"], "how many achievemenst in minecraft")
        self.assertEqual(body["correction"], "local")

    def test_a_search_with_nothing_to_fix_says_nothing(self):
        with self._search_with():
            body = self._post("achievements in minecraft").json()
        self.assertEqual(self.seen, ["achievements in minecraft"])
        self.assertIsNone(body["corrected_from"])
        self.assertIsNone(body["correction"])

    def test_search_instead_searches_what_was_typed(self):
        with self._search_with():
            body = self._post("achievemenst", exact=True).json()
        self.assertEqual(self.seen, ["achievemenst"])
        self.assertEqual(body["query"], "achievemenst")
        self.assertIsNone(body["corrected_from"])

    def test_no_ai_stays_out_of_the_fix(self):
        with self._search_with():
            body = self._post("achievemenst !ai").json()
        self.assertEqual(self.seen, ["achievements"])
        self.assertTrue(body["used_no_ai"])
        self.assertEqual(body["corrected_from"], "achievemenst")

    def test_the_fix_covers_other_tabs_too(self):
        with self._search_with():
            body = self._post("achievemenst", category="images").json()
        self.assertEqual(self.seen, ["achievements"])
        self.assertEqual(body["query"], "achievements")

    def test_the_answer_cards_are_picked_for_the_fixed_query(self):
        # the converter card only recognises "kilometers"
        with self._search_with():
            body = self._post("5 kilomters to miles").json()
        self.assertEqual(self.seen, ["5 kilometers to miles"])
        self.assertEqual(body["answer_kind"], "units")

    def test_an_engine_fix_searches_again_with_it(self):
        # google pse and searxng answer for the typed words and only name the fix
        with self._search_with(
            {"engine_correction": "tft patch notes", "engine_correction_applied": False}
        ):
            body = self._post("tft patchnotes").json()
        self.assertEqual(self.seen, ["tft patchnotes", "tft patch notes"])
        self.assertEqual(body["query"], "tft patch notes")
        self.assertEqual(body["corrected_from"], "tft patchnotes")
        self.assertEqual(body["correction"], "engine")
        self.assertNotIn("engine_correction", body)

    def test_brave_already_searched_its_fix(self):
        with self._search_with(
            {"engine_correction": "tft patch notes", "engine_correction_applied": True}
        ):
            body = self._post("tft patchnotes").json()
        self.assertEqual(self.seen, ["tft patchnotes"])
        self.assertEqual(body["query"], "tft patch notes")
        self.assertEqual(body["corrected_from"], "tft patchnotes")

    def test_the_local_fix_wins_over_an_engines(self):
        with self._search_with({"engine_correction": "something else entirely"}):
            body = self._post("achievemenst").json()
        self.assertEqual(self.seen, ["achievements"])
        self.assertEqual(body["correction"], "local")

    def test_an_engine_fix_is_ignored_when_the_owner_asked_for_exact(self):
        with self._search_with({"engine_correction": "tft patch notes"}):
            body = self._post("tft patchnotes", exact=True).json()
        self.assertEqual(self.seen, ["tft patchnotes"])
        self.assertIsNone(body["corrected_from"])

    def test_an_engine_fix_that_rewrites_the_search_is_ignored(self):
        with self._search_with({"engine_correction": "completely unrelated words"}):
            body = self._post("tft patchnotes").json()
        self.assertEqual(self.seen, ["tft patchnotes"])
        self.assertIsNone(body["corrected_from"])

    def test_a_missing_package_leaves_the_search_alone(self):
        with (
            mock.patch.dict(sys.modules, {"spellchecker": None}),
            self._search_with(),
        ):
            andromeda_spelling._checker.cache_clear()
            body = self._post("achievemenst").json()
        self.assertEqual(self.seen, ["achievemenst"])
        self.assertIsNone(body["corrected_from"])

    def test_the_correct_route_gives_only_the_local_fix(self):
        with self._search_with():
            fixed = self.client.post("/api/andromeda/correct", json={"query": "achievemenst !ai"})
            same = self.client.post("/api/andromeda/correct", json={"query": "achievements"})
        self.assertEqual(fixed.json(), {"query": "achievements", "corrected_from": "achievemenst"})
        self.assertEqual(same.json(), {"query": "achievements", "corrected_from": None})
        self.assertEqual(self.seen, [])

    def test_the_answer_route_fixes_the_same_way(self):
        seen = []

        async def fake_resolve(found, strict=False):
            seen.append(found)
            return {"kind": found["kind"]}

        with mock.patch("services.andromeda_answers.resolve", side_effect=fake_resolve):
            self.client.post("/api/andromeda/answer", json={"query": "5 kilomters to miles"})
            self.client.post(
                "/api/andromeda/answer", json={"query": "5 kilomters to miles", "exact": True}
            )
        self.assertEqual(len(seen), 1)
        self.assertEqual(seen[0]["kind"], "units")

    def test_the_overview_is_written_for_the_fixed_query(self):
        db = self.db()
        db.add(
            ModelEndpoint(
                name="local",
                base_url="http://127.0.0.1:11434/v1",
                cached_models='["overview-model"]',
                enabled=True,
            )
        )
        db.commit()
        db.close()
        calls = []

        async def stream(*args, **kwargs):
            calls.append(str(kwargs.get("messages") or args))
            yield {"delta": "SKIP"}

        andromeda._OVERVIEW_CACHE.clear()
        snippet = "Minecraft has 122 achievements that players can earn in survival mode."
        with self._search_with(
            {"results": [{"url": "https://wiki.example.com/a", "title": "a", "snippet": snippet}]}
        ):
            found = self._post("achievemenst").json()
        # the page sends the search's own query to the overview
        with mock.patch("services.llm.stream_chat", new=stream):
            self.client.post(
                "/api/andromeda/overview",
                json={"query": found["query"], "results": found["overview_seed"]},
            )
        self.assertTrue(calls)
        self.assertIn("achievements", calls[0])
        self.assertNotIn("achievemenst", calls[0])


class EngineFixTest(ApiTest):
    def test_brave_google_and_searxng_fixes_reach_the_report(self):
        class Reply:
            def __init__(self, data):
                self._data = data

            def raise_for_status(self):
                pass

            def json(self):
                return self._data

        class Client:
            def __init__(self, data):
                self._data = data

            async def __aenter__(self):
                return self

            async def __aexit__(self, *_):
                return False

            async def get(self, *_args, **_kwargs):
                return Reply(self._data)

        import asyncio

        brave = {
            "query": {"altered": "achievements"},
            "web": {"results": [{"url": "https://a.test", "title": "a", "description": "b"}]},
        }
        google = {
            "spelling": {"correctedQuery": "achievements"},
            "items": [{"link": "https://a.test", "title": "a", "snippet": "b"}],
        }
        with mock.patch.object(research_search.httpx, "AsyncClient", lambda **_: Client(brave)):
            rows = asyncio.run(research_search._search_brave("achievemenst", "key"))
        self.assertEqual((rows.correction, rows.correction_applied), ("achievements", True))
        with mock.patch.object(research_search.httpx, "AsyncClient", lambda **_: Client(google)):
            rows = asyncio.run(research_search._search_google_pse("achievemenst", "k", "cx"))
        self.assertEqual((rows.correction, rows.correction_applied), ("achievements", False))
        self.assertEqual(len(rows), 1)

    def test_a_fix_with_no_results_still_reaches_the_report(self):
        rows = research_search.Rows()
        rows.correction = "achievements"

        async def provider(*_args, **_kwargs):
            return rows

        import asyncio

        with mock.patch.object(research_search, "_search_provider", side_effect=provider):
            report = asyncio.run(
                research_search.search_chain_report("achievemenst", override="google_pse")
            )
        self.assertEqual(report.results, [])
        self.assertEqual(report.correction, "achievements")
        self.assertFalse(report.correction_applied)
