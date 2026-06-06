import unittest

from services import agent_runtime as ar


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
