import asyncio
import unittest
from unittest import mock

from services.research import deep_research as dr
from services.research.deep_research import DeepResearcher, current_date_context
from services.research import research_utils as ru
from services.research import search as rs


class UtilTests(unittest.TestCase):
    def test_html_to_text_strips_tags_and_chrome(self):
        html = "<nav>menu</nav><p>Hello <b>world</b></p><script>bad()</script>"
        out = rs._html_to_text(html)
        self.assertIn("Hello", out)
        self.assertIn("world", out)
        self.assertNotIn("bad()", out)
        self.assertNotIn("<", out)

    def test_low_quality_filter(self):
        self.assertTrue(ru.is_low_quality("This page is just a cookie consent banner"))
        self.assertTrue(ru.is_low_quality(""))
        self.assertTrue(ru.is_low_quality(None))
        self.assertFalse(ru.is_low_quality("Mars has two moons, Phobos and Deimos."))

    def test_strip_think_paired_and_trailing(self):
        self.assertEqual(ru.strip_think("<think>hmm</think>answer"), "answer")
        self.assertEqual(ru.strip_think("reasoning here</think>final"), "final")
        self.assertIsNone(ru.strip_think(None))

    def test_date_context_has_year(self):
        from datetime import datetime

        self.assertIn(str(datetime.now().year), current_date_context())


class JsonParseTests(unittest.TestCase):
    def setUp(self):
        self.r = DeepResearcher("http://x", "k", "m")

    def test_plain_array(self):
        self.assertEqual(self.r._parse_json_array('["a", "b"]'), ["a", "b"])

    def test_code_fenced_array(self):
        self.assertEqual(self.r._parse_json_array('```json\n["a","b"]\n```'), ["a", "b"])

    def test_echoed_example_keeps_last(self):
        # model echoes the prompt's Example: [...] then gives the real answer
        txt = 'Example: ["query one", "query two"]\nHere you go:\n["real one", "real two"]'
        self.assertEqual(self.r._parse_json_array(txt), ["real one", "real two"])

    def test_truncated_array_repair(self):
        self.assertEqual(self.r._parse_json_array('["one", "two", "thr'), ["one", "two"])

    def test_object_parse(self):
        out = self.r._parse_json_object('blah {"summary": "s", "evidence": "e"} trailing')
        self.assertEqual(out["summary"], "s")


# ── full loop against fakes ──────────────────────────────────────────────────


def _fake_response(prompt: str) -> str:
    p = prompt
    if "research strategist" in p:
        return '{"sub_questions":["a","b"],"key_topics":["t"],"success_criteria":"c"}'
    if "Classify this research question" in p:
        return "general"
    if "JSON array of query strings" in p:
        import re

        m = re.search(r"\*\*Round:\*\*\s*(\d+)", p)
        rn = m.group(1) if m else "0"
        return f'["query {rn}a", "query {rn}b"]'  # unique per round, else dedup empties it
    if "Webpage Content" in p:  # extractor
        return '{"rational":"r","evidence":"the moon is made of rock","summary":"rocky moon"}'
    if "deciding whether a research report" in p:  # STOP_PROMPT
        return "YES — the report is comprehensive."
    # synthesize / final report
    return "## Report\n\n" + ("detailed analysis paragraph. " * 120)


async def _fake_stream_chat(messages, base_url, api_key, model, **kw):
    text = _fake_response(messages[-1]["content"])
    yield {"delta": text}
    yield {"done": True, "usage": {}}


async def _fake_search_chain(query, override=None, max_results=10):
    return (
        [{"url": f"http://ex/{abs(hash(query)) % 999}", "title": "Ex", "snippet": "s"}],
        "duckduckgo",
        None,
    )


def _fake_fetch(url, timeout=10):
    return {
        "success": True,
        "content": "the moon is made of rock " * 50,
        "title": "Ex",
        "og_image": "",
    }


class FullLoopTests(unittest.TestCase):
    def test_research_produces_report(self):
        with (
            mock.patch("services.llm.stream_chat", _fake_stream_chat),
            mock.patch("services.research.search.search_chain", _fake_search_chain),
            mock.patch("services.research.search.fetch_webpage_content", _fake_fetch),
        ):
            r = DeepResearcher("http://x", "k", "m", min_rounds=1, max_rounds=2)
            report = asyncio.run(r.research("what is the moon made of"))

        self.assertIsInstance(report, str)
        self.assertGreater(len(report), 100)
        self.assertGreaterEqual(r.round_count, 1)
        self.assertIn("duckduckgo", r.providers_used)
        self.assertTrue(r.urls_fetched)
        self.assertTrue(r.findings)

    def test_search_down_returns_message(self):
        async def _empty_search(query, override=None, max_results=10):
            return ([], None, "duckduckgo: connection refused")

        with (
            mock.patch("services.llm.stream_chat", _fake_stream_chat),
            mock.patch("services.research.search.search_chain", _empty_search),
            mock.patch("services.research.search.fetch_webpage_content", _fake_fetch),
        ):
            # min_rounds high so the stop-check doesn't fire before the empty
            # rounds accumulate to the "search down" threshold
            r = DeepResearcher("http://x", "k", "m", min_rounds=3, max_rounds=3, max_empty_rounds=2)
            report = asyncio.run(r.research("anything"))
        self.assertIn("Search unavailable", report)


if __name__ == "__main__":
    unittest.main()
