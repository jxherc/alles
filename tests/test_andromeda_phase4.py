import asyncio
import json
import os
import random
import string
from unittest import mock

from core.database import AndromedaSavedSearch, JarvisWorkflow, ModelEndpoint, Project, Session
from core.settings import load_settings, save_settings
from services import andromeda
from tests._client import ApiTest


class AndromedaParserPropertyTest(ApiTest):
    def test_only_standalone_no_ai_tokens_are_removed(self):
        parsed = andromeda.parse_query("!g python !ai docs !gh")
        self.assertEqual(parsed.query, "!g python docs !gh")
        self.assertFalse(parsed.overview)
        self.assertTrue(parsed.used_no_ai)
        for value in ("!aim", "x!ai", "!ai,", "not!ai", "! AI"):
            with self.subTest(value=value):
                kept = andromeda.parse_query(value)
                self.assertEqual(kept.query, value)
                self.assertTrue(kept.overview)

    def test_inserting_no_ai_preserves_every_other_random_token(self):
        rng = random.Random(404)
        alphabet = string.ascii_letters + string.digits + "!_-.:/"
        for _ in range(500):
            tokens = []
            for _ in range(rng.randrange(0, 20)):
                token = "".join(rng.choice(alphabet) for _ in range(rng.randrange(1, 30)))
                if token.casefold() == "!ai":
                    token += "x"
                tokens.append(token)
            position = rng.randrange(len(tokens) + 1)
            request = tokens[:position] + [rng.choice(["!ai", "!AI", "!Ai"])] + tokens[position:]
            parsed = andromeda.parse_query(" \t ".join(request))
            self.assertEqual(parsed.query, " ".join(tokens))
            self.assertFalse(parsed.overview)


class AndromedaEvidenceTest(ApiTest):
    def test_key_answer_rejects_a_long_claim_instead_of_truncating_it(self):
        answer = andromeda.short_key_answer(
            "FastAPI uses Python type hints to validate requests and produce detailed error messages automatically.",
            "how does FastAPI validate requests",
        )
        self.assertEqual(answer, "")

        qualified = andromeda.short_key_answer(
            "This treatment is generally safe for adults but should not be used during pregnancy.",
            "is this treatment safe",
        )
        self.assertEqual(qualified, "")

        multi_sentence = andromeda.short_key_answer(
            "This treatment is safe for adults. Do not use it during pregnancy.",
            "is this treatment safe",
        )
        self.assertEqual(
            multi_sentence,
            "This treatment is safe for adults. Do not use it during pregnancy.",
        )

    def test_key_answer_is_a_short_full_sentence(self):
        answer = andromeda.short_key_answer(
            "Fluorine is the 9th element on the periodic table.",
            "what is the 9th element",
        )
        self.assertEqual(answer, "Fluorine is the 9th element on the periodic table.")

        definition = andromeda.short_key_answer(
            "Python is a programming language.",
            "what is Python",
        )
        self.assertEqual(definition, "Python is a programming language.")

    def test_answer_focus_must_be_short_exact_and_repeated_by_evidence(self):
        text = "SQLite 3.50.4 is the latest stable release."
        quotes = ["SQLite 3.50.4 is the latest stable release with planner fixes."]
        self.assertEqual(andromeda.verified_answer_focus(text, "3.50.4", quotes), "3.50.4")
        self.assertEqual(
            andromeda.verified_answer_focus(text, "sqlite 3.50.4", quotes),
            "SQLite 3.50.4",
        )
        self.assertEqual(andromeda.verified_answer_focus(text, "latest", quotes), "latest")
        self.assertEqual(andromeda.verified_answer_focus(text, "4.0", quotes), "")
        self.assertEqual(andromeda.verified_answer_focus(text, "3.50.4", ["SQLite"]), "")

    def test_verified_long_claim_stays_complete_without_a_key_answer(self):
        claim = (
            "This treatment is generally safe for adults but should not be used during "
            "pregnancy without medical guidance."
        )
        evidence = [
            {
                "id": "s1",
                "title": "medical guidance",
                "url": "https://docs.example.com/docs/treatment",
                "publisher": "docs.example.com",
                "source_kind": "official docs",
                "source_quality": 1,
                "dates": [],
                "versions": [],
                "passages": [claim],
            }
        ]
        raw = json.dumps(
            {
                "claims": [
                    {
                        "text": claim,
                        "citations": [{"source_id": "s1", "quote": claim}],
                    }
                ]
            }
        )
        checked = andromeda.verify_overview(raw, "treatment safety", evidence)
        self.assertEqual(checked["status"], "ready")
        self.assertEqual(checked["key_answer"], {})
        self.assertEqual(checked["claims"][0]["text"], claim)

    def test_result_normalization_drops_unsafe_shapes_and_duplicates(self):
        rows = [
            {"url": "javascript:alert(1)", "title": "bad"},
            {"url": "https://user:pass@example.com/private", "title": "credentials"},
            {"url": "https://docs.example.com/docs/v2", "title": "docs", "snippet": "  hi  "},
            {"url": "https://docs.example.com/docs/v2", "title": "duplicate"},
        ]
        result = andromeda.normalize_results(rows, "fixture", 12)
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["source_kind"], "official docs")
        self.assertEqual(result[0]["snippet"], "hi")

    def test_result_normalization_keeps_provider_media_metadata(self):
        result = andromeda.normalize_results(
            [
                {
                    "url": "https://news.example/article",
                    "title": "story",
                    "publisher": "Example News",
                    "favicon_url": "https://news.example/favicon.png",
                    "thumbnail_url": "https://cdn.example/thumb.webp",
                    "image_url": "https://cdn.example/full.webp",
                    "published": "2026-07-14T10:00:00Z",
                    "width": 1600,
                    "height": 900,
                }
            ],
            "fixture",
            12,
        )
        self.assertEqual(result[0]["publisher"], "Example News")
        self.assertEqual(result[0]["favicon_url"], "https://news.example/favicon.png")
        self.assertEqual((result[0]["width"], result[0]["height"]), (1600, 900))

    def test_claim_needs_an_exact_quote_from_its_named_source(self):
        evidence = [
            {
                "id": "s1",
                "title": "release",
                "url": "https://example.com/releases",
                "publisher": "example.com",
                "source_kind": "release notes",
                "source_quality": 2,
                "dates": ["2026-07-10"],
                "versions": ["2.4.0"],
                "passages": ["Version 2.4.0 was released on 2026-07-10 with safer defaults."],
            }
        ]
        raw = json.dumps(
            {
                "claims": [
                    {
                        "text": "Version 2.4.0 has safer defaults.",
                        "citations": [
                            {
                                "source_id": "s1",
                                "quote": "Version 2.4.0 was released on 2026-07-10 with safer defaults.",
                            }
                        ],
                    },
                    {
                        "text": "It is maintained by twelve people.",
                        "citations": [{"source_id": "s1", "quote": "twelve maintainers"}],
                    },
                ]
            }
        )
        checked = andromeda.verify_overview(raw, "software version", evidence)
        self.assertEqual(checked["status"], "ready")
        self.assertEqual(len(checked["claims"]), 1)
        self.assertEqual(checked["key_answer"]["source_claim_index"], 0)
        self.assertEqual(checked["key_answer"]["focus"], "2.4.0")
        self.assertEqual(checked["rejected_claims"], 1)
        self.assertEqual(checked["freshness"]["newest_version_seen"], "2.4.0")

    def test_exact_but_unrelated_quote_cannot_support_a_claim(self):
        quote = "The Eiffel Tower is located in Paris and opened to visitors in 1889."
        evidence = [
            {
                "id": "s1",
                "title": "unrelated docs",
                "url": "https://docs.example.com/docs/landmarks",
                "publisher": "docs.example.com",
                "source_kind": "official docs",
                "source_quality": 1,
                "dates": [],
                "versions": [],
                "passages": [quote],
            }
        ]
        raw = json.dumps(
            {
                "claims": [
                    {
                        "text": "FastAPI uses Python type hints for request validation.",
                        "citations": [{"source_id": "s1", "quote": quote}],
                    }
                ]
            }
        )
        checked = andromeda.verify_overview(raw, "FastAPI request validation", evidence)
        self.assertEqual(checked["status"], "insufficient_evidence")
        self.assertEqual(checked["rejected_claims"], 1)

    def test_claim_numbers_versions_and_entities_must_match_its_quotes(self):
        quote = "Python 3.12 supports the stable API on 2026-07-10."
        evidence = [
            {
                "id": "s1",
                "title": "python docs",
                "url": "https://docs.python.org/docs/stable",
                "publisher": "docs.python.org",
                "source_kind": "official docs",
                "source_quality": 1,
                "dates": ["2026-07-10"],
                "versions": ["3.12"],
                "passages": [quote],
            }
        ]
        for claim in (
            "Python 3.13 supports the stable API on 2026-07-10.",
            "Ruby 3.12 supports the stable API on 2026-07-10.",
            "Python 3.12 supports the stable API on 2026-07-11.",
        ):
            with self.subTest(claim=claim):
                raw = json.dumps(
                    {
                        "claims": [
                            {
                                "text": claim,
                                "citations": [{"source_id": "s1", "quote": quote}],
                            }
                        ]
                    }
                )
                checked = andromeda.verify_overview(raw, "stable API", evidence)
                self.assertEqual(checked["status"], "insufficient_evidence")

    def test_stale_version_cannot_be_called_latest(self):
        evidence = [
            {
                "id": "s1",
                "title": "old",
                "url": "https://example.com/releases/2.3",
                "publisher": "example.com",
                "source_kind": "release notes",
                "source_quality": 2,
                "dates": [],
                "versions": ["2.3.0"],
                "passages": ["Version 2.3.0 was released."],
            },
            {
                "id": "s2",
                "title": "new",
                "url": "https://example.com/releases/2.4",
                "publisher": "example.com",
                "source_kind": "release notes",
                "source_quality": 2,
                "dates": [],
                "versions": ["2.4.0"],
                "passages": ["Version 2.4.0 was released."],
            },
        ]
        raw = json.dumps(
            {
                "claims": [
                    {
                        "text": "Version 2.3.0 is the latest release.",
                        "citations": [{"source_id": "s1", "quote": "Version 2.3.0 was released."}],
                    }
                ]
            }
        )
        self.assertEqual(
            andromeda.verify_overview(raw, "latest software version", evidence)["status"],
            "insufficient_evidence",
        )

    def test_community_quote_cannot_support_a_latest_claim(self):
        evidence = [
            {
                "id": "s1",
                "title": "forum post",
                "url": "https://forum.example/posts/one",
                "publisher": "forum.example",
                "source_kind": "community",
                "source_quality": 5,
                "dates": ["2026-07-12"],
                "versions": ["9.0.0"],
                "passages": ["Version 9.0.0 is the latest release."],
            }
        ]
        raw = json.dumps(
            {
                "claims": [
                    {
                        "text": "Version 9.0.0 is the latest release.",
                        "citations": [
                            {"source_id": "s1", "quote": "Version 9.0.0 is the latest release."}
                        ],
                    }
                ]
            }
        )
        checked = andromeda.verify_overview(raw, "latest software version", evidence)
        self.assertEqual(checked["status"], "insufficient_evidence")
        self.assertEqual(checked["rejected_claims"], 1)

    def test_latest_claim_uses_freshest_primary_when_community_source_conflicts(self):
        evidence = [
            {
                "id": "s1",
                "title": "release notes",
                "url": "https://example.com/releases/4.0.0",
                "publisher": "example.com",
                "source_kind": "release notes",
                "source_quality": 2,
                "dates": ["2026-07-10"],
                "versions": ["4.0.0"],
                "passages": ["Version 4.0.0 was released on 2026-07-10."],
            },
            {
                "id": "s2",
                "title": "forum guess",
                "url": "https://forum.example/posts/future",
                "publisher": "forum.example",
                "source_kind": "community",
                "source_quality": 5,
                "dates": ["2026-07-12"],
                "versions": ["9.0.0"],
                "passages": ["A forum user says Version 9.0.0 is the latest release."],
            },
        ]
        raw = json.dumps(
            {
                "claims": [
                    {
                        "text": "Version 4.0.0 is the latest release.",
                        "citations": [
                            {
                                "source_id": "s1",
                                "quote": "Version 4.0.0 was released on 2026-07-10.",
                            }
                        ],
                    }
                ]
            }
        )
        checked = andromeda.verify_overview(raw, "latest software version", evidence)
        self.assertEqual(checked["status"], "ready")
        self.assertEqual(checked["freshness"]["newest_version_seen"], "9.0.0")
        self.assertEqual(checked["freshness"]["newest_primary_version_seen"], "4.0.0")

    def test_evidence_candidates_are_quality_first_and_stable_within_quality(self):
        rows = [
            *[
                {"url": f"https://forum.example/post/{index}", "title": f"forum {index}"}
                for index in range(6)
            ],
            {"url": "https://docs.example.com/docs/first", "title": "docs first"},
            {"url": "https://docs.example.com/docs/second", "title": "docs second"},
        ]

        def fetch(url, _timeout):
            return {
                "success": True,
                "title": url,
                "content": "FastAPI request validation uses Python type hints for stable behavior.",
            }

        with (
            mock.patch.object(andromeda, "is_safe_url", return_value=True),
            mock.patch("services.research.search.fetch_webpage_content", side_effect=fetch),
        ):
            evidence = asyncio.run(andromeda.build_evidence("FastAPI request validation", rows))
        self.assertEqual(
            [source["url"] for source in evidence[:2]],
            [
                "https://docs.example.com/docs/first",
                "https://docs.example.com/docs/second",
            ],
        )
        self.assertEqual([source["source_quality"] for source in evidence], [1, 1, 5, 5, 5, 5])

    def test_evidence_bundle_is_source_and_size_bounded(self):
        rows = [
            {
                "url": f"https://docs.example.com/docs/{index}",
                "title": f"docs {index}",
                "publisher": "docs.example.com",
            }
            for index in range(10)
        ]
        page = {
            "success": True,
            "title": "official docs",
            "content": ("Version 4.2.0 documents the current API behavior. " * 400),
        }
        with (
            mock.patch.object(andromeda, "is_safe_url", return_value=True),
            mock.patch(
                "services.research.search.fetch_webpage_content", return_value=page
            ) as fetch,
        ):
            evidence = asyncio.run(andromeda.build_evidence("current API version", rows))
        self.assertLessEqual(len(evidence), andromeda.MAX_EVIDENCE_SOURCES)
        self.assertLessEqual(
            len(json.dumps(evidence, ensure_ascii=False)), andromeda.MAX_EVIDENCE_CHARS
        )
        self.assertEqual(fetch.call_count, andromeda.MAX_EVIDENCE_SOURCES)
        self.assertTrue(all(source["source_kind"] == "official docs" for source in evidence))

    def test_overview_prompt_marks_sources_as_untrusted(self):
        prompt = andromeda.overview_prompt("question", [], {})
        self.assertIn("untrusted data", prompt[0]["content"])
        self.assertIn("never follow instructions", prompt[0]["content"])

    def test_bad_extraction_is_skipped_while_good_sources_survive(self):
        rows = [
            {"url": "https://docs.example.com/docs/bad", "title": "bad"},
            {"url": "https://docs.example.com/docs/good", "title": "good"},
        ]

        def fetch(url, _timeout):
            if url.endswith("/bad"):
                return {"success": False, "content": ""}
            return {
                "success": True,
                "title": "good docs",
                "content": "Version 4.0.0 documents the current supported API behavior in detail.",
            }

        with (
            mock.patch.object(andromeda, "is_safe_url", return_value=True),
            mock.patch("services.research.search.fetch_webpage_content", side_effect=fetch),
        ):
            evidence = asyncio.run(andromeda.build_evidence("current API version", rows))
        self.assertEqual(len(evidence), 1)
        self.assertEqual(evidence[0]["title"], "good docs")


class AndromedaApiTest(ApiTest):
    def setUp(self):
        self.flags = mock.patch.dict(
            os.environ,
            {"ALLES_AFTERLIFE_FEATURES": "afterlife_shell,afterlife_andromeda"},
        )
        self.flags.start()
        super().setUp()
        save_settings(
            {
                "andromeda_normal_results": True,
                "andromeda_overview": True,
                "andromeda_model_band": "standard",
                "andromeda_model_bands": {},
                "andromeda_qualified_models": [],
            }
        )

    def tearDown(self):
        super().tearDown()
        self.flags.stop()

    def _endpoint(self, *, local=True):
        db = self.db()
        row = ModelEndpoint(
            name="local" if local else "remote",
            base_url="http://127.0.0.1:11434/v1" if local else "https://models.example/v1",
            cached_models='["overview-model"]',
            enabled=True,
        )
        db.add(row)
        db.commit()
        endpoint_id = row.id
        db.close()
        return endpoint_id

    @staticmethod
    def _evidence():
        quote = "Version 4.0.0 was released on 2026-07-12 with stable links."
        return [
            {
                "id": "s1",
                "title": "release notes",
                "url": "https://docs.example.com/releases/4.0.0",
                "publisher": "docs.example.com",
                "source_kind": "release notes",
                "source_quality": 2,
                "dates": ["2026-07-12"],
                "versions": ["4.0.0"],
                "passages": [quote],
            }
        ]

    @staticmethod
    def _overview_raw():
        return json.dumps(
            {
                "claims": [
                    {
                        "text": "Version 4.0.0 is the latest release with stable links.",
                        "citations": [
                            {
                                "source_id": "s1",
                                "quote": "Version 4.0.0 was released on 2026-07-12 with stable links.",
                            }
                        ],
                    }
                ]
            }
        )

    def test_no_ai_keeps_normal_result_order_and_changes_only_overview(self):
        fixture = {
            "status": "ready",
            "results": [{"rank": 1, "url": "https://example.com", "title": "one"}],
            "provider": "fixture",
            "elapsed_ms": 4,
            "error": "",
        }

        async def fake(*_args, **_kwargs):
            return fixture

        with mock.patch.object(andromeda, "normal_search", side_effect=fake):
            normal = self.client.post("/api/andromeda/search", json={"query": "python docs"})
            no_ai = self.client.post("/api/andromeda/search", json={"query": "python !ai docs"})
        self.assertEqual(normal.status_code, 200)
        self.assertEqual(normal.json()["results"], no_ai.json()["results"])
        self.assertTrue(normal.json()["overview_requested"])
        self.assertFalse(no_ai.json()["overview_requested"])
        self.assertEqual(no_ai.json()["query"], "python docs")

    def test_image_search_accepts_thirty_results_and_reports_another_page(self):
        rows = [
            {"url": f"https://images.example/{index}", "title": f"image {index}"}
            for index in range(31)
        ]
        chain = mock.AsyncMock(return_value=(rows, "fixture", None))
        with mock.patch("services.research.search.search_chain", new=chain):
            response = self.client.post(
                "/api/andromeda/search",
                json={"query": "nebula", "category": "images", "max_results": 30},
            )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.json()["results"]), 30)
        self.assertTrue(response.json()["has_more"])
        self.assertEqual(chain.await_args.kwargs["max_results"], 45)

    def test_normal_search_honors_the_twenty_result_setting(self):
        rows = [
            {"url": f"https://example.test/{index}", "title": f"result {index}"}
            for index in range(21)
        ]
        chain = mock.AsyncMock(return_value=(rows, "fixture", None))
        with mock.patch("services.research.search.search_chain", new=chain):
            response = self.client.post(
                "/api/andromeda/search",
                json={"query": "configured count", "max_results": 20},
            )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.json()["results"]), 20)
        self.assertTrue(response.json()["has_more"])
        self.assertEqual(chain.await_args.kwargs["max_results"], 30)

    def test_filtered_first_page_keeps_later_provider_rows_reachable(self):
        all_rows = [
            {"url": "javascript:unsafe", "title": "unsafe"},
            {"url": "https://example.test/0", "title": "result 0"},
            {"url": "https://example.test/0", "title": "duplicate 0"},
            {"url": "https://example.test/1", "title": "result 1"},
            {"url": "https://example.test/1", "title": "duplicate 1"},
            {"url": "https://example.test/2", "title": "result 2"},
            {"url": "https://example.test/2", "title": "duplicate 2"},
            {"url": "https://example.test/3", "title": "result 3"},
            {"url": "https://example.test/3", "title": "duplicate 3"},
            {"url": "https://example.test/4", "title": "result 4"},
            {"url": "https://example.test/5", "title": "later result"},
        ]

        async def provider(_query, **kwargs):
            return all_rows[: kwargs["max_results"]], "fixture", None

        chain = mock.AsyncMock(side_effect=provider)
        with mock.patch("services.research.search.search_chain", new=chain):
            response = self.client.post(
                "/api/andromeda/search",
                json={"query": "filtered", "max_results": 5},
            )
            continuation = self.client.post(
                "/api/andromeda/search",
                json={"query": "filtered", "max_results": 10},
            )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.json()["results"]), 5)
        self.assertTrue(response.json()["has_more"])
        self.assertEqual(chain.await_args_list[0].kwargs["max_results"], 10)
        self.assertEqual(continuation.status_code, 200)
        self.assertIn(
            "https://example.test/5",
            [row["url"] for row in continuation.json()["results"]],
        )
        self.assertFalse(continuation.json()["has_more"])
        self.assertEqual(
            [call.kwargs["max_results"] for call in chain.await_args_list],
            [10, 20, 15],
        )

    def test_duplicate_full_batches_do_not_claim_an_unreachable_next_page(self):
        async def provider(_query, **kwargs):
            rows = [
                {"url": "https://example.test/only", "title": f"duplicate {index}"}
                for index in range(kwargs["max_results"])
            ]
            return rows, "fixture", None

        chain = mock.AsyncMock(side_effect=provider)
        with (
            mock.patch("services.research.search.search_chain", new=chain),
            mock.patch.object(andromeda, "MAX_NORMAL_FETCH_RESULTS", 12),
        ):
            response = self.client.post(
                "/api/andromeda/search",
                json={"query": "duplicates", "max_results": 5},
            )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.json()["results"]), 1)
        self.assertFalse(response.json()["has_more"])
        self.assertEqual(
            [call.kwargs["max_results"] for call in chain.await_args_list],
            [10, 12],
        )

    def test_ordinary_search_never_expands_to_the_category_result_ceiling(self):
        async def provider(_query, **kwargs):
            rows = [
                {"url": "https://example.test/only", "title": f"duplicate {index}"}
                for index in range(kwargs["max_results"])
            ]
            return rows, "fixture", None

        chain = mock.AsyncMock(side_effect=provider)
        with mock.patch("services.research.search.search_chain", new=chain):
            response = self.client.post(
                "/api/andromeda/search",
                json={"query": "bounded duplicates", "max_results": 20},
            )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.json()["results"]), 1)
        self.assertFalse(response.json()["has_more"])
        self.assertEqual(
            [call.kwargs["max_results"] for call in chain.await_args_list],
            [30, andromeda.MAX_NORMAL_FETCH_RESULTS],
        )

    def test_dead_search_media_returns_a_quiet_local_placeholder(self):
        with mock.patch(
            "services.net_guard.safe_get_public_async",
            new=mock.AsyncMock(side_effect=RuntimeError("upstream unavailable")),
        ):
            response = self.client.get(
                "/api/andromeda/media",
                params={"url": "https://images.example.test/dead.jpg"},
            )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.headers["x-andromeda-media-state"], "unavailable")
        self.assertEqual(response.headers["content-type"], "image/svg+xml")
        self.assertIn(b"media unavailable", response.content)

    def test_provider_exhaustion_hides_the_next_page(self):
        rows = [
            {"url": f"https://news.example/{index}", "title": f"story {index}"}
            for index in range(20)
        ]
        with mock.patch(
            "services.research.search.search_chain",
            new=mock.AsyncMock(return_value=(rows, "fixture", None)),
        ):
            response = self.client.post(
                "/api/andromeda/search",
                json={"query": "release", "category": "news", "max_results": 20},
            )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.json()["results"]), 20)
        self.assertFalse(response.json()["has_more"])

    def test_andromeda_api_is_hidden_without_its_exact_flag(self):
        with mock.patch.dict(os.environ, {"ALLES_AFTERLIFE_FEATURES": "afterlife_shell"}):
            response = self.client.post("/api/andromeda/search", json={"query": "hidden"})
        self.assertEqual(response.status_code, 404)

    def test_normal_results_and_overview_are_independent(self):
        async def fixture(*_args, **_kwargs):
            return {
                "status": "ready",
                "results": [{"url": "https://example.com", "title": "evidence"}],
                "provider": "fixture",
                "elapsed_ms": 3,
                "error": "",
            }

        with mock.patch.object(andromeda, "normal_search", side_effect=fixture) as search:
            response = self.client.post(
                "/api/andromeda/search",
                json={"query": "anything", "normal_results": False, "overview": True},
            )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["status"], "disabled")
        self.assertEqual(len(response.json()["overview_seed"]), 1)
        self.assertTrue(response.json()["overview_requested"])
        search.assert_awaited_once()

    def test_both_disabled_skips_every_search_provider(self):
        with mock.patch("services.research.search.search_chain", new=mock.AsyncMock()) as provider:
            response = self.client.post(
                "/api/andromeda/search",
                json={"query": "anything", "normal_results": False, "overview": False},
            )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["status"], "disabled")
        self.assertFalse(response.json()["overview_requested"])
        self.assertEqual(response.json()["results"], [])
        provider.assert_not_awaited()

    def test_provider_menu_only_marks_configured_engines_available(self):
        save_settings(
            {
                "search_provider": "searxng",
                "searxng_url": "http://127.0.0.1:8888",
                "brave_api_key": "secret",
            }
        )
        response = self.client.get("/api/andromeda/providers")
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["selected"], "searxng")
        providers = {row["value"]: row["available"] for row in payload["providers"]}
        self.assertTrue(providers["searxng"])
        self.assertTrue(providers["brave"])
        self.assertTrue(providers["duckduckgo"])
        self.assertFalse(providers["serper"])
        self.assertFalse(providers["tavily"])

    def test_global_overview_setting_is_independent_from_normal_results(self):
        save_settings({"andromeda_overview": False, "andromeda_normal_results": True})

        async def fixture(*_args, **_kwargs):
            return {
                "status": "ready",
                "results": [{"url": "https://example.com", "title": "one"}],
                "provider": "fixture",
                "elapsed_ms": 2,
                "error": "",
            }

        with mock.patch.object(andromeda, "normal_search", side_effect=fixture):
            response = self.client.post("/api/andromeda/search", json={"query": "one"})
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json()["normal_results_enabled"])
        self.assertFalse(response.json()["overview_requested"])
        self.assertEqual(len(response.json()["results"]), 1)

    def test_provider_timeout_and_partial_results_keep_clear_states(self):
        cases = (
            (
                {
                    "status": "error",
                    "results": [],
                    "provider": "",
                    "elapsed_ms": 1500,
                    "error": "all providers timed out",
                },
                "error",
            ),
            (
                {
                    "status": "partial",
                    "results": [{"url": "https://example.com", "title": "one"}],
                    "provider": "fixture",
                    "elapsed_ms": 90,
                    "error": "second provider timed out",
                },
                "partial",
            ),
        )
        for payload, expected in cases:
            with (
                self.subTest(expected=expected),
                mock.patch.object(
                    andromeda, "normal_search", new=mock.AsyncMock(return_value=payload)
                ),
            ):
                response = self.client.post(
                    "/api/andromeda/search", json={"query": "current software docs"}
                )
                self.assertEqual(response.status_code, 200)
                self.assertEqual(response.json()["status"], expected)
                self.assertEqual(response.json()["error"], payload["error"])

    def test_search_report_exposes_safe_failure_and_attempted_sources(self):
        from services.research import search as search_service

        async def provider(name, *_args):
            if name == "brave":
                raise TimeoutError("secret token should never leave the provider")
            return []

        settings = {
            "research_search_provider": "brave",
            "search_fallback_chain": ["wikipedia"],
        }
        with (
            mock.patch("core.settings.load_settings", return_value=settings),
            mock.patch.object(search_service, "_search_provider", side_effect=provider),
        ):
            report = asyncio.run(search_service.search_chain_report("current docs", max_results=5))
            legacy = asyncio.run(search_service.search_chain("current docs", max_results=5))
            normal = asyncio.run(andromeda.normal_search("current docs", max_results=5))

        self.assertEqual(report.failure_type, "timeout")
        self.assertEqual(report.attempted_sources, ("brave", "wikipedia", "duckduckgo"))
        self.assertNotIn("secret token", report.error)
        rows, used, error = legacy
        self.assertEqual((rows, used), ([], None))
        self.assertEqual(error, report.error)
        self.assertEqual(normal["failure_type"], "timeout")
        self.assertEqual(normal["attempted_sources"], ["brave", "wikipedia", "duckduckgo"])
        self.assertNotIn("secret token", normal["error"])

    def test_successful_fallback_reports_every_attempt_in_order(self):
        from services.research import search as search_service

        async def provider(name, *_args):
            if name == "brave":
                raise RuntimeError("provider detail is private")
            if name == "wikipedia":
                return [{"url": "https://example.com", "title": "answer", "snippet": "hit"}]
            return []

        settings = {
            "research_search_provider": "brave",
            "search_fallback_chain": ["wikipedia"],
        }
        with (
            mock.patch("core.settings.load_settings", return_value=settings),
            mock.patch.object(search_service, "_search_provider", side_effect=provider),
        ):
            result = asyncio.run(andromeda.normal_search("answer", max_results=5))

        self.assertEqual(result["status"], "ready")
        self.assertEqual(result["provider"], "wikipedia")
        self.assertEqual(result["failure_type"], "")
        self.assertEqual(result["attempted_sources"], ["brave", "wikipedia"])

    def test_explicit_provider_does_not_silently_switch_to_duckduckgo(self):
        from services.research import search as search_service

        async def provider(name, *_args):
            if name == "searxng":
                raise search_service.SearchProviderFailure("configuration")
            return [{"url": "https://duckduckgo.com", "title": "wrong provider"}]

        with (
            mock.patch(
                "core.settings.load_settings",
                return_value={"search_fallback_chain": ["duckduckgo"]},
            ),
            mock.patch.object(search_service, "_search_provider", side_effect=provider),
        ):
            report = asyncio.run(
                search_service.search_chain_report("answer", override="searxng", max_results=5)
            )

        self.assertEqual(report.results, [])
        self.assertEqual(report.attempted_sources, ("searxng",))
        self.assertEqual(report.failure_type, "configuration")

    def test_unknown_provider_name_is_redacted_from_safe_diagnostics(self):
        from services.research import search as search_service

        secret_name = "provider-key-topsecret"
        settings = {
            "research_search_provider": secret_name,
            "search_fallback_chain": [],
        }
        with (
            mock.patch("core.settings.load_settings", return_value=settings),
            mock.patch.object(
                search_service,
                "_search_provider",
                new=mock.AsyncMock(side_effect=RuntimeError("private provider detail")),
            ),
        ):
            report = asyncio.run(search_service.search_chain_report("answer", max_results=5))

        self.assertEqual(report.attempted_sources[0], "unknown")
        self.assertNotIn(secret_name, repr(report))
        self.assertNotIn("private provider detail", repr(report))

    def test_external_searxng_setting_requires_https_without_credentials(self):
        for value in (
            "http://search.example",
            "https://user:secret@search.example",
            "javascript:alert(1)",
        ):
            with self.subTest(value=value):
                response = self.client.patch("/api/settings", json={"searxng_url": value})
                self.assertEqual(response.status_code, 400)
                self.assertEqual(response.json()["code"], "invalid_searxng_url")

    def test_external_searxng_search_uses_the_redirect_safe_fetcher(self):
        from services.research import search as search_service

        response = mock.Mock()
        response.raise_for_status.return_value = None
        response.json.return_value = {
            "results": [{"url": "https://example.com", "title": "one", "content": "hit"}]
        }
        with mock.patch(
            "services.net_guard.safe_get_async", new=mock.AsyncMock(return_value=response)
        ) as safe:
            rows = asyncio.run(
                search_service._search_searxng("python !gh", "https://search.example", 5)
            )
        self.assertEqual(rows[0]["title"], "one")
        self.assertIn("q=python+%21gh", safe.await_args.args[0])

    def test_isolated_managed_searxng_port_uses_the_local_client(self):
        from services.research import search as search_service

        response = mock.Mock()
        response.raise_for_status.return_value = None
        response.json.return_value = {
            "results": [{"url": "https://example.com", "title": "one", "content": "hit"}]
        }
        local_client = mock.Mock()
        local_client.get = mock.AsyncMock(return_value=response)
        local_client.aclose = mock.AsyncMock()
        with (
            mock.patch(
                "services.managed_searxng.managed_url", return_value="http://127.0.0.1:8890"
            ),
            mock.patch("httpx.AsyncClient", return_value=local_client),
        ):
            rows = asyncio.run(search_service._search_searxng("python", "http://127.0.0.1:8890", 5))
        self.assertEqual(rows[0]["title"], "one")
        self.assertGreaterEqual(local_client.get.await_count, 1)
        local_client.aclose.assert_awaited_once()

    def test_overview_never_uses_remote_model_without_exact_confirmation(self):
        endpoint_id = self._endpoint(local=False)
        denied = self.client.post(
            "/api/andromeda/overview",
            json={"query": "current docs", "results": []},
        )
        self.assertEqual(denied.status_code, 409)
        self.assertEqual(denied.json()["code"], "remote_model_confirmation_required")
        preview = self.client.get("/api/andromeda/overview/preview").json()
        self.assertEqual(preview["endpoint_id"], endpoint_id)
        self.assertEqual(preview["privacy_class"], "remote")

    def test_no_model_is_a_clear_setup_error_while_search_still_works(self):
        overview = self.client.post(
            "/api/andromeda/overview", json={"query": "docs", "results": []}
        )
        self.assertEqual(overview.status_code, 409)
        self.assertEqual(overview.json()["code"], "model_unavailable")

    def test_overview_stream_emits_verified_claims_and_model_provenance(self):
        self._endpoint(local=True)
        complete = mock.AsyncMock(return_value=self._overview_raw())
        with (
            mock.patch.object(
                andromeda, "build_evidence", new=mock.AsyncMock(return_value=self._evidence())
            ),
            mock.patch("services.llm.simple_complete", new=complete),
        ):
            response = self.client.post(
                "/api/andromeda/overview",
                json={
                    "query": "latest software version",
                    "results": [{"url": "https://docs.example.com/releases/4.0.0"}],
                },
            )
        self.assertEqual(response.status_code, 200)
        events = response.text
        self.assertIn('"type": "model"', events)
        self.assertIn('"type": "evidence"', events)
        self.assertIn('"type": "claim"', events)
        self.assertIn('"status": "ready"', events)
        self.assertIn("data: [DONE]", events)
        self.assertFalse(complete.await_args.kwargs["thinking"])
        self.assertLessEqual(complete.await_args.kwargs["max_tokens"], 450)

    def test_bad_output_failure_and_timeout_preserve_recovery_events(self):
        self._endpoint(local=True)
        for result, code in (
            ("not json", "insufficient_evidence"),
            (RuntimeError("local model stopped"), "overview_failed"),
            (TimeoutError(), "overview_timeout"),
        ):
            complete = (
                mock.AsyncMock(side_effect=result)
                if isinstance(result, Exception)
                else mock.AsyncMock(return_value=result)
            )
            with (
                self.subTest(code=code),
                mock.patch.object(
                    andromeda, "build_evidence", new=mock.AsyncMock(return_value=self._evidence())
                ),
                mock.patch("services.llm.simple_complete", new=complete),
            ):
                response = self.client.post(
                    "/api/andromeda/overview",
                    json={
                        "query": "current software version",
                        "results": [{"url": "https://docs.example.com/releases/4.0.0"}],
                    },
                )
                self.assertEqual(response.status_code, 200)
                self.assertIn(code, response.text)
                self.assertIn("data: [DONE]", response.text)

    def test_bad_extraction_never_calls_the_model(self):
        self._endpoint(local=True)
        complete = mock.AsyncMock()
        with (
            mock.patch.object(andromeda, "build_evidence", new=mock.AsyncMock(return_value=[])),
            mock.patch("services.llm.simple_complete", new=complete),
        ):
            response = self.client.post(
                "/api/andromeda/overview",
                json={
                    "query": "current docs",
                    "results": [{"url": "https://docs.example.com/docs/current"}],
                },
            )
        self.assertEqual(response.status_code, 200)
        self.assertIn("insufficient_evidence", response.text)
        complete.assert_not_awaited()

    def test_auto_qualification_requires_two_exact_supported_claims(self):
        endpoint_id = self._endpoint(local=True)
        raw = json.dumps(
            {
                "claims": [
                    {
                        "text": "Version 3.2.0 was released on 2026-07-01.",
                        "citations": [
                            {
                                "source_id": "s1",
                                "quote": "Version 3.2.0 was released on 2026-07-01.",
                            }
                        ],
                    },
                    {
                        "text": "Offline links remain available when overview generation fails.",
                        "citations": [
                            {
                                "source_id": "s1",
                                "quote": "The release notes say offline links remain available when overview generation fails.",
                            }
                        ],
                    },
                ]
            }
        )
        with mock.patch("services.llm.simple_complete", new=mock.AsyncMock(return_value=raw)):
            response = self.client.post(
                "/api/andromeda/models/qualify",
                json={"endpoint_id": endpoint_id, "model": "overview-model"},
            )
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json()["passed"])
        self.assertEqual(response.json()["supported_claims"], 2)
        self.assertIn(
            f"{endpoint_id}:overview-model", load_settings()["andromeda_qualified_models"]
        )

    def test_saved_search_roundtrip_and_delete(self):
        payload = {
            "query": "saved query",
            "request": {"overview": True, "band": "standard", "has_more": False},
            "results": [{"url": "https://example.com", "title": "example"}],
            "overview": {"status": "ready", "claims": []},
            "evidence": [{"id": "s1", "passages": ["exact evidence"]}],
            "model": {"model": "local"},
            "verification": {
                "status": "checked",
                "checked_on": "2026-07-24",
                "verdicts": [{"claim_index": 0, "verdict": "verified"}],
            },
            "verifier_model": {"model": "local-verifier"},
        }
        saved = self.client.post("/api/andromeda/saved", json=payload)
        self.assertEqual(saved.status_code, 200)
        search_id = saved.json()["id"]
        reopened = self.client.get(f"/api/andromeda/saved/{search_id}").json()
        self.assertEqual(reopened["request"], payload["request"])
        self.assertEqual(reopened["results"], payload["results"])
        self.assertEqual(reopened["evidence"], payload["evidence"])
        self.assertEqual(reopened["verification"], payload["verification"])
        self.assertEqual(reopened["verifier_model"], payload["verifier_model"])
        self.assertEqual(len(self.client.get("/api/andromeda/saved").json()["searches"]), 1)
        self.assertEqual(self.client.delete(f"/api/andromeda/saved/{search_id}").status_code, 200)
        db = self.db()
        self.assertIsNone(db.get(AndromedaSavedSearch, search_id))
        db.close()

    def test_deep_research_keeps_the_selected_project_and_query(self):
        self._endpoint(local=True)
        db = self.db()
        project = Project(name="research", working_dir="/tmp/research")
        db.add(project)
        db.flush()
        session = Session(name="search", project_id=project.id, mode="chat")
        db.add(session)
        db.commit()
        project_id, session_id = project.id, session.id
        db.close()
        with mock.patch("services.jarvis_handoff.launch", return_value=True):
            response = self.client.post(
                "/api/andromeda/deep-research",
                json={"query": "verify phase four", "session_id": session_id},
            )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["project_id"], project_id)
        self.assertEqual(response.json()["session_id"], session_id)
        db = self.db()
        workflow = db.get(JarvisWorkflow, response.json()["id"])
        if workflow is None:
            from core.database import JarvisRun

            run = db.get(JarvisRun, response.json()["id"])
            workflow = db.get(JarvisWorkflow, run.workflow_id)
        self.assertIn("verify phase four", workflow.prompt)
        db.close()
