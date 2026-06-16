import json
import unittest

from services import agent_runtime as ar


class CapToolContentTests(unittest.TestCase):
    def test_large_output_stays_valid_json(self):
        tc = {"output": "Z" * 50000, "error": False}
        content = ar._cap_tool_content(tc)
        # the old bug: sliced the json string + tacked on `"}` → unparseable
        parsed = json.loads(content)   # must not raise
        self.assertFalse(parsed["error"])
        self.assertIn("truncated for context", parsed["output"])
        self.assertLess(len(content), 20000)
        # head AND tail of the original are preserved
        self.assertTrue(parsed["output"].startswith("Z"))
        self.assertTrue(parsed["output"].rstrip().endswith("Z"))

    def test_small_output_untouched(self):
        tc = {"output": "hello", "error": False}
        self.assertEqual(json.loads(ar._cap_tool_content(tc)), tc)

    def test_hist_chars_counts_image_urls(self):
        msgs = [{"role": "user", "content": [
            {"type": "text", "text": "hi"},
            {"type": "image_url", "image_url": {"url": "data:image/png;base64," + "A" * 5000}},
        ]}]
        self.assertGreaterEqual(ar._hist_chars(msgs), 5000)


class TrimHistoryTests(unittest.TestCase):
    def _convo(self, n, size):
        msgs = [{"role": "system", "content": "sys"}]
        for i in range(n):
            msgs.append({"role": "assistant", "content": "",
                         "tool_calls": [{"call_id": f"c{i}", "name": "shell", "args": {}}]})
            msgs.append({"role": "tool", "tool_call_id": f"c{i}", "content": "X" * size})
        return msgs

    def test_preserves_structure_and_bounds(self):
        msgs = self._convo(20, 10000)
        before = len(msgs)
        ar._trim_history(msgs, budget=50000, keep_recent=4)
        # never removes messages (assistant<->tool pairing must stay valid)
        self.assertEqual(len(msgs), before)
        total = sum(len(m["content"]) for m in msgs if isinstance(m.get("content"), str))
        self.assertLessEqual(total, 70000)
        # system + most recent tool output untouched
        self.assertEqual(msgs[0]["content"], "sys")
        self.assertEqual(len(msgs[-1]["content"]), 10000)

    def test_under_budget_is_noop(self):
        msgs = self._convo(2, 100)
        snapshot = [m["content"] for m in msgs]
        ar._trim_history(msgs, budget=100000)
        self.assertEqual([m["content"] for m in msgs], snapshot)


class EffortTurnsTests(unittest.TestCase):
    def test_system_note_mentions_effort(self):
        note_low = ar.agent_system_note({"agent_effort": "low"})
        note_high = ar.agent_system_note({"agent_effort": "high"})
        self.assertIn("EFFORT: low", note_low)
        self.assertIn("EFFORT: high", note_high)


if __name__ == "__main__":
    unittest.main()
