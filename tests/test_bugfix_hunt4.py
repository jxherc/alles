"""regression tests for bugs found in the 4th bug-hunt iteration:
- a non-finite (nan/inf) settings value must not persist + brick every settings read
- a malicious feed must not trigger billion-laughs entity expansion
"""

import json
import math
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

os.environ["AUTH_ENABLED"] = "false"


class SettingsFiniteTests(unittest.TestCase):
    def setUp(self):
        import core.settings as cs

        self.cs = cs
        self.tmp = Path(tempfile.mkdtemp()) / "settings.json"
        self._p = mock.patch.object(cs, "_SETTINGS_FILE", self.tmp)
        self._p.start()

    def tearDown(self):
        self._p.stop()

    def test_non_finite_dropped_and_file_valid(self):
        self.cs.save_settings({"tts_speed": math.inf, "tax_setaside_rate": float("nan")})
        raw = self.tmp.read_text("utf-8")
        # the written file must be strict JSON (no Infinity/NaN literals)
        self.assertNotIn("Infinity", raw)
        self.assertNotIn("NaN", raw)
        parsed = json.loads(raw)  # would raise if invalid
        self.assertNotIn("tts_speed", parsed)  # the poison key was dropped -> falls back to default

    def test_finite_value_kept(self):
        self.cs.save_settings({"tax_setaside_rate": 0.3})
        self.assertEqual(json.loads(self.tmp.read_text("utf-8"))["tax_setaside_rate"], 0.3)

    def test_nested_non_finite_dropped(self):
        self.cs.save_settings({"some_obj": {"a": 1.0, "b": math.inf}})
        obj = json.loads(self.tmp.read_text("utf-8"))["some_obj"]
        self.assertEqual(obj, {"a": 1.0})


class FeedEntityBombTests(unittest.TestCase):
    def test_billion_laughs_neutralized(self):
        from services import read_feeds

        bomb = (
            '<?xml version="1.0"?>'
            "<!DOCTYPE lolz ["
            '<!ENTITY lol "lol">'
            '<!ENTITY lol2 "&lol;&lol;&lol;&lol;&lol;&lol;&lol;&lol;&lol;&lol;">'
            '<!ENTITY lol3 "&lol2;&lol2;&lol2;&lol2;&lol2;&lol2;&lol2;&lol2;&lol2;&lol2;">'
            "]>"
            "<rss><channel><title>&lol3;</title></channel></rss>"
        )
        out = read_feeds.parse_feed(bomb)
        # the DOCTYPE/entities are stripped, so &lol3; is undefined -> parse fails -> empty result.
        # the key property is it returns fast without expanding the entity.
        self.assertIsInstance(out, dict)
        self.assertNotIn("lollollol", json.dumps(out))

    def test_normal_feed_still_parses(self):
        from services import read_feeds

        feed = (
            "<rss><channel><title>My Feed</title>"
            "<item><title>Post One</title><link>https://x.com/1</link></item>"
            "</channel></rss>"
        )
        out = read_feeds.parse_feed(feed)
        self.assertEqual(out["title"], "My Feed")
        self.assertTrue(any(it["title"] == "Post One" for it in out["items"]))


if __name__ == "__main__":
    unittest.main()
