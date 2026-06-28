"""stream_execute (the agent's tool dispatcher) must turn a dispatch-level error into a tool-error
result the model can correct — not let it abort the whole agent turn. the classic case: the model
passes a non-numeric `limit`, so int() raises in the dispatch BEFORE the tool body's own try/except."""

import asyncio
import unittest

from services import agent_tools as at


def _run_stream(name, args):
    async def go():
        return [ev async for ev in at.stream_execute(name, args)]

    return asyncio.run(go())


class StreamExecuteTest(unittest.TestCase):
    def test_non_numeric_limit_is_graceful_error(self):
        events = _run_stream("github_list_repos", {"limit": "ten"})
        results = [e["result"] for e in events if e.get("type") == "result"]
        self.assertEqual(len(results), 1)
        self.assertTrue(results[0]["error"])
        self.assertIn("failed", results[0]["output"])

    def test_execute_directly_still_raises(self):
        # documents WHY the wrapper exists: the dispatch int() crash is real
        with self.assertRaises(ValueError):
            asyncio.run(at.execute("github_list_repos", {"limit": "ten"}))
