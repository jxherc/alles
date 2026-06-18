from services.audio_overview import format_script
from tests._client import ApiTest


class FormatScriptTests(ApiTest):
    def test_summary_single_speaker(self):
        segs = format_script("First point. Second point.", "summary")
        self.assertTrue(segs)
        self.assertTrue(all(s["speaker"] == "Narrator" for s in segs))

    def test_summary_splits_paragraphs(self):
        raw = "Para one here.\n\nPara two here.\n\nPara three."
        segs = format_script(raw, "summary")
        self.assertEqual(len(segs), 3)

    def test_podcast_two_speakers(self):
        raw = "Alex: Welcome to the show.\nSam: Glad to be here.\nAlex: Let's dig in."
        segs = format_script(raw, "podcast")
        speakers = [s["speaker"] for s in segs]
        self.assertEqual(speakers, ["Alex", "Sam", "Alex"])

    def test_podcast_strips_labels(self):
        segs = format_script("Alex: hello there\nSam: hi back", "podcast")
        self.assertEqual(segs[0]["text"], "hello there")
        self.assertNotIn("Alex:", segs[0]["text"])

    def test_strips_markdown_bold_and_headings(self):
        segs = format_script("# Title\n\nThis is **bold** and _italic_ text.", "summary")
        joined = " ".join(s["text"] for s in segs)
        self.assertNotIn("#", joined)
        self.assertNotIn("**", joined)
        self.assertNotIn("_italic_", joined)
        self.assertIn("bold", joined)

    def test_strips_code_fences(self):
        raw = "Intro line.\n\n```python\nprint('x')\n```\n\nOutro line."
        segs = format_script(raw, "summary")
        joined = " ".join(s["text"] for s in segs)
        self.assertNotIn("```", joined)
        self.assertNotIn("print('x')", joined)

    def test_drops_empty_lines(self):
        segs = format_script("Alex: hi\n\n\nSam:   \nAlex: still here", "podcast")
        self.assertTrue(all(s["text"].strip() for s in segs))

    def test_merges_consecutive_same_speaker(self):
        raw = "Alex: one\nAlex: two\nSam: three"
        segs = format_script(raw, "podcast")
        self.assertEqual([s["speaker"] for s in segs], ["Alex", "Sam"])
        self.assertIn("one", segs[0]["text"])
        self.assertIn("two", segs[0]["text"])

    def test_long_segment_capped(self):
        long = "word " * 400  # ~2000 chars
        segs = format_script(long, "summary")
        self.assertTrue(all(len(s["text"]) <= 600 for s in segs))

    def test_unknown_style_defaults_summary(self):
        segs = format_script("Hello world.", "bogus")
        self.assertTrue(all(s["speaker"] == "Narrator" for s in segs))

    def test_empty_input(self):
        self.assertEqual(format_script("", "summary"), [])
        self.assertEqual(format_script("   \n\n  ", "podcast"), [])

    def test_podcast_no_labels_falls_back_alternating(self):
        # if the model ignored the host format, still produce alternating segments
        raw = "First thought here.\n\nSecond thought here."
        segs = format_script(raw, "podcast")
        self.assertEqual(len(segs), 2)
        self.assertNotEqual(segs[0]["speaker"], segs[1]["speaker"])


class AudioOverviewEndpointTests(ApiTest):
    def setUp(self):
        super().setUp()
        import services.audio_overview as ao

        async def _fake(messages, base_url, api_key, model, max_tokens=256):
            return "Alex: Here is the overview.\nSam: That makes sense."

        self._orig = ao.simple_complete
        ao.simple_complete = _fake
        # an enabled endpoint with a cached model so the route can resolve one
        from core.database import ModelEndpoint

        d = self.db()
        ep = ModelEndpoint(name="t", base_url="http://x", api_key="", enabled=True)
        ep.cached_models = '["m1"]'
        d.add(ep)
        d.commit()
        d.close()

    def tearDown(self):
        import services.audio_overview as ao

        ao.simple_complete = self._orig
        super().tearDown()

    def _session_with_text(self):
        from core.database import Message, Session

        d = self.db()
        s = Session(name="s", mode="chat")
        d.add(s)
        d.flush()
        d.add(Message(session_id=s.id, role="user", content="explain photosynthesis"))
        d.add(Message(session_id=s.id, role="assistant", content="Plants turn light into energy."))
        d.commit()
        sid = s.id
        d.close()
        return sid

    def test_endpoint_from_session(self):
        sid = self._session_with_text()
        r = self.client.post("/api/audio-overview", json={"session_id": sid, "style": "podcast"})
        self.assertEqual(r.status_code, 200)
        d = r.json()
        self.assertEqual(d["style"], "podcast")
        self.assertTrue(d["segments"])
        self.assertEqual(d["segments"][0]["speaker"], "Alex")

    def test_endpoint_no_source_400(self):
        r = self.client.post("/api/audio-overview", json={"style": "summary"})
        self.assertEqual(r.status_code, 400)

    def test_endpoint_unknown_session_404(self):
        r = self.client.post("/api/audio-overview", json={"session_id": "nope"})
        self.assertEqual(r.status_code, 404)
