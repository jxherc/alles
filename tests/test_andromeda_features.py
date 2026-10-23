import asyncio
import json
from unittest import mock

from core.settings import save_settings
from services import andromeda
from tests._client import ApiTest

EVIDENCE = [
    {
        "id": "s1",
        "title": "Tailscale serve",
        "url": "https://tailscale.com/docs/serve",
        "publisher": "tailscale.com",
        "source_kind": "official",
        "source_quality": 1,
        "dates": [],
        "versions": [],
        "passages": ["Tailscale serve shares a local service with devices in your tailnet."],
    }
]


class FollowUpTest(ApiTest):
    def test_overview_returns_clean_follow_ups(self):
        raw = json.dumps(
            {
                "claims": [
                    {
                        "text": "Tailscale serve shares a local service with devices.",
                        "focus": "",
                        "citations": [
                            {
                                "source_id": "s1",
                                "quote": "Tailscale serve shares a local service with devices",
                            }
                        ],
                    }
                ],
                "follow_ups": [
                    "How is serve different from funnel?",
                    "how is serve different from funnel?",
                    "see https://evil.example for more",
                    "short",
                    "Does serve need HTTPS certificates?",
                    "Can serve expose a TCP port?",
                ],
            }
        )
        checked = andromeda.verify_overview(raw, "tailscale serve", EVIDENCE)
        self.assertEqual(checked["status"], "ready")
        self.assertEqual(
            checked["follow_ups"],
            [
                "How is serve different from funnel?",
                "Does serve need HTTPS certificates?",
                "Can serve expose a TCP port?",
            ],
        )

    def test_no_follow_ups_without_a_supported_answer(self):
        raw = json.dumps({"claims": [], "follow_ups": ["What else is there to know?"]})
        self.assertEqual(andromeda.verify_overview(raw, "q", EVIDENCE)["follow_ups"], [])

    def test_vague_follow_ups_search_with_the_earlier_question(self):
        self.assertEqual(
            andromeda.follow_up_query("how much does it cost?", "tailscale funnel"),
            "tailscale funnel how much does it cost?",
        )
        self.assertEqual(andromeda.follow_up_query("pricing", "exa search"), "exa search pricing")
        self.assertEqual(
            andromeda.follow_up_query("how does the wireguard handshake work", "tailscale funnel"),
            "how does the wireguard handshake work",
        )
        self.assertEqual(andromeda.follow_up_query("it costs?", ""), "it costs?")

    def test_prompt_carries_the_thread_and_the_deeper_limit(self):
        context = [{"question": f"q{n}", "answer": "a" * 900} for n in range(5)]
        messages = andromeda.overview_prompt("q", EVIDENCE, {}, context=context, deep=True)
        bundle = json.loads(messages[1]["content"])
        self.assertEqual([turn["question"] for turn in bundle["earlier"]], ["q2", "q3", "q4"])
        self.assertTrue(all(len(turn["answer"]) <= 600 for turn in bundle["earlier"]))
        self.assertIn("at most five claims", messages[0]["content"])
        self.assertIn("follow_ups", messages[0]["content"])
        plain = andromeda.overview_prompt("q", EVIDENCE, {})
        self.assertNotIn("earlier", json.loads(plain[1]["content"]))
        self.assertIn("at most three claims", plain[0]["content"])

    def test_deeper_reads_more_sources(self):
        rows = [{"url": f"https://site{n}.dev/page", "title": "t"} for n in range(12)]
        fetched = []

        def page(url, timeout):
            fetched.append(url)
            return {"success": True, "content": "tailscale serve works well", "title": "t"}

        with (
            mock.patch("services.research.search.fetch_webpage_content", side_effect=page),
            mock.patch("services.andromeda.is_safe_url", return_value=True),
        ):
            asyncio.run(andromeda.build_evidence("tailscale serve", rows))
            normal = len(fetched)
            fetched.clear()
            asyncio.run(andromeda.build_evidence("tailscale serve", rows, deep=True))
        self.assertEqual(normal, andromeda.MAX_EVIDENCE_SOURCES)
        self.assertEqual(len(fetched), andromeda.DEEP_EVIDENCE_SOURCES)


class BlockedSitesTest(ApiTest):
    def test_site_names_are_cleaned(self):
        self.assertEqual(
            andromeda.blocked_sites(
                ["https://www.Pinterest.com/pin/1", "pinterest.com", "quora.com:443", "nope", ""]
            ),
            ["pinterest.com", "quora.com"],
        )

    def test_blocked_sites_and_their_subdomains_leave_the_results(self):
        rows = [
            {"url": "https://www.pinterest.com/a"},
            {"url": "https://uk.pinterest.com/b"},
            {"url": "https://notpinterest.com/c"},
            {"url": "https://docs.dev/d"},
        ]
        kept = andromeda.drop_blocked(rows, ["pinterest.com"])
        self.assertEqual(
            [r["url"] for r in kept], ["https://notpinterest.com/c", "https://docs.dev/d"]
        )

    def test_settings_validate_and_clean_the_list(self):
        r = self.client.patch(
            "/api/settings",
            json={"andromeda_blocked_sites": ["https://www.quora.com/x", "quora.com"]},
        )
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json()["andromeda_blocked_sites"], ["quora.com"])
        bad = self.client.patch("/api/settings", json={"andromeda_blocked_sites": ["not a site"]})
        self.assertEqual(bad.status_code, 400)

    def test_normal_search_drops_blocked_sites(self):
        save_settings({"andromeda_blocked_sites": ["spam.dev"]})
        rows = [
            {"url": "https://spam.dev/x", "title": "x"},
            {"url": "https://good.dev/y", "title": "y"},
        ]

        class Chain(tuple):
            failure_type = ""
            attempted_sources = ("duckduckgo",)

        async def chain(*_args, **_kwargs):
            return Chain((rows, "duckduckgo", None))

        with mock.patch("services.research.search.search_chain", side_effect=chain):
            result = asyncio.run(andromeda.normal_search("q", max_results=5))
        save_settings({"andromeda_blocked_sites": []})
        self.assertEqual([r["url"] for r in result["results"]], ["https://good.dev/y"])


class RemoteConsentTest(ApiTest):
    def test_preview_says_whether_to_ask_each_search(self):
        selected = mock.Mock()
        selected.public.return_value = {"model": "m", "endpoint": "e", "privacy_class": "remote"}
        flag = mock.patch.dict("os.environ", {"ALLES_AFTERLIFE_FEATURES": "afterlife_andromeda"})
        with flag, mock.patch("services.andromeda.select_overview_model", return_value=selected):
            save_settings({"andromeda_confirm_remote": False})
            quiet = self.client.get("/api/andromeda/overview/preview").json()
            save_settings({"andromeda_confirm_remote": True})
            asked = self.client.get("/api/andromeda/overview/preview").json()
        save_settings({"andromeda_confirm_remote": False})
        self.assertFalse(quiet["confirm_each_search"])
        self.assertTrue(asked["confirm_each_search"])

    def test_fact_check_preview_follows_the_same_setting(self):
        selected = mock.Mock()
        selected.public.return_value = {"model": "m", "endpoint": "e", "privacy_class": "remote"}
        flag = mock.patch.dict("os.environ", {"ALLES_AFTERLIFE_FEATURES": "afterlife_andromeda"})
        with (
            flag,
            mock.patch("services.andromeda_verifier.should_verify", return_value=True),
            mock.patch("services.model_resolver.resolve_model", return_value=selected),
        ):
            save_settings({"andromeda_confirm_remote": True})
            asked = self.client.post("/api/andromeda/verification/preview", json={"query": "q"})
        save_settings({"andromeda_confirm_remote": False})
        self.assertEqual(asked.status_code, 200, asked.text)
        self.assertTrue(asked.json()["confirm_each_search"])


class FastOverviewTest(ApiTest):
    ROWS = [
        {
            "url": "https://docs.example.dev/a",
            "title": "A",
            "snippet": "Tailscale serve shares a local service with devices in your tailnet over HTTPS.",
        },
        {
            "url": "https://blog.example.dev/b",
            "title": "B",
            "snippet": "Funnel is like serve but it also exposes the service to the public internet.",
        },
        {"url": "https://short.example.dev/c", "title": "C", "snippet": "too short"},
    ]

    def test_snippets_become_citable_passages_without_fetching(self):
        with (
            mock.patch("services.andromeda.is_safe_url", return_value=True),
            mock.patch("services.research.search.fetch_webpage_content") as fetch,
        ):
            evidence = asyncio.run(
                andromeda.build_evidence("tailscale serve", self.ROWS, fast=True)
            )
        fetch.assert_not_called()
        self.assertEqual(
            [e["url"] for e in evidence],
            ["https://docs.example.dev/a", "https://blog.example.dev/b"],
        )
        self.assertEqual(evidence[0]["passages"], [self.ROWS[0]["snippet"]])
        self.assertEqual(evidence[0]["id"], "s1")

    def test_thin_snippets_fall_back_to_reading_pages(self):
        thin = [{"url": "https://x.dev/a", "title": "x", "snippet": "short"}]

        def page(url, timeout):
            return {"success": True, "content": "tailscale serve shares a service", "title": "x"}

        with (
            mock.patch("services.andromeda.is_safe_url", return_value=True),
            mock.patch("services.research.search.fetch_webpage_content", side_effect=page) as fetch,
        ):
            asyncio.run(andromeda.build_evidence("tailscale serve", thin, fast=True))
        fetch.assert_called_once()
