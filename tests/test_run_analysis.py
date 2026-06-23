"""stage 3e - agent run analysis + replay. tests first (RED)."""

import json
import os
import unittest

os.environ["AUTH_ENABLED"] = "false"
from services import run_analysis as ra


def _run(rid, intent, tools, status="done", turns=3):
    return {
        "id": rid,
        "intent": intent,
        "status": status,
        "turn": turns,
        "model": "claude-opus-4-8",
        "started_at": "2026-06-23T10:00:00",
        "finished_at": "2026-06-23T10:01:30",
        "tool_steps": [{"name": t} for t in tools],
        "events": [],
    }


class SummaryTests(unittest.TestCase):
    def test_summarize(self):
        s = ra.summarize(_run("r1", "fix the money bug", ["grep_files", "read_file", "edit_file"]))
        self.assertEqual(s["id"], "r1")
        self.assertEqual(s["intent"], "fix the money bug")
        self.assertEqual(s["tools"], ["grep_files", "read_file", "edit_file"])
        self.assertEqual(s["status"], "done")
        self.assertEqual(s["turns"], 3)
        self.assertAlmostEqual(s["duration_sec"], 90.0, places=1)

    def test_summarize_dedupes_tools_preserving_order(self):
        s = ra.summarize(_run("r1", "x", ["read_file", "read_file", "edit_file"]))
        self.assertEqual(s["tools"], ["read_file", "edit_file"])


class ClusterTests(unittest.TestCase):
    def test_clusters_same_intent(self):
        runs = [
            _run("a", "add a money forecast", ["read_file"]),
            _run("b", "add a money forecast", ["edit_file"]),
            _run("c", "write the readme", ["write_file"]),
        ]
        clusters = ra.cluster_by_intent(runs)
        sizes = sorted(len(v) for v in clusters.values())
        self.assertEqual(sizes, [1, 2])

    def test_toolsig_fallback_when_no_intent(self):
        runs = [
            _run("a", "", ["read_file", "edit_file"]),
            _run("b", "", ["read_file", "edit_file"]),
        ]
        clusters = ra.cluster_by_intent(runs)
        self.assertEqual(len(clusters), 1)  # grouped by tool signature


class PrecedentTests(unittest.TestCase):
    def test_only_successful(self):
        runs = [
            _run("ok", "build a mail rule", ["edit_file"], status="done"),
            _run("bad", "build a mail rule", ["edit_file"], status="error"),
        ]
        p = ra.precedents(runs, "build a mail rule", k=5)
        ids = [x["id"] for x in p]
        self.assertIn("ok", ids)
        self.assertNotIn("bad", ids)

    def test_ranks_by_overlap(self):
        runs = [
            _run("close", "build a mail rule engine", ["edit_file"]),
            _run("far", "totally unrelated photo album", ["write_file"]),
        ]
        p = ra.precedents(runs, "build a mail rule", k=5)
        self.assertEqual(p[0]["id"], "close")

    def test_k_limits(self):
        runs = [_run(str(i), "same intent here", ["read_file"]) for i in range(10)]
        self.assertEqual(len(ra.precedents(runs, "same intent here", k=3)), 3)

    def test_no_match_empty(self):
        runs = [_run("a", "build mail", ["x"])]
        self.assertEqual(ra.precedents(runs, "xyzzy nothing matches", k=5), [])

    def test_precedents_text(self):
        runs = [_run("a", "build a mail rule", ["edit_file", "shell"])]
        txt = ra.precedents_text(runs, "build a mail rule")
        self.assertIn("mail rule", txt)
        self.assertIn("edit_file", txt)


class ReplayTests(unittest.TestCase):
    def test_replay_plan_overrides(self):
        run = _run("r1", "do the thing", ["read_file"])
        plan = ra.replay_plan(run, model="claude-haiku-4-5", effort="low")
        self.assertEqual(plan["model"], "claude-haiku-4-5")
        self.assertEqual(plan["effort"], "low")
        self.assertEqual(plan["messages"][-1]["content"], "do the thing")

    def test_replay_plan_keeps_original_model_when_not_overridden(self):
        run = _run("r1", "x", [])
        plan = ra.replay_plan(run)
        self.assertEqual(plan["model"], "claude-opus-4-8")


class LoadTests(unittest.TestCase):
    def test_load_runs_from_disk(self):
        import tempfile
        from pathlib import Path

        d = Path(tempfile.mkdtemp())
        (d / "r1.json").write_text(json.dumps(_run("r1", "hi", ["read_file"])), "utf-8")
        from services import agent_state

        orig = agent_state.DATA_DIR
        agent_state.DATA_DIR = d
        try:
            runs = ra.load_runs(limit=10)
        finally:
            agent_state.DATA_DIR = orig
        self.assertTrue(any(r["id"] == "r1" for r in runs))

    def test_empty_graceful(self):
        self.assertEqual(ra.cluster_by_intent([]), {})
        self.assertEqual(ra.precedents([], "x"), [])


if __name__ == "__main__":
    unittest.main()
