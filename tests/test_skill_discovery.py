"""stage 3f - semantic skill discovery + feedback. tests first (RED)."""

import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

os.environ["AUTH_ENABLED"] = "false"
from services import skills_store as ss


class _Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self._p = mock.patch.object(ss, "SKILLS_DIR", Path(self.tmp.name))
        self._p.start()

    def tearDown(self):
        self._p.stop()
        self.tmp.cleanup()


class FeedbackTests(_Base):
    def test_record_feedback_bumps(self):
        ss.upsert_skill("Editor", "copy editor", "tidy prose", "do it")
        ss.record_feedback("editor", True)
        ss.record_feedback("editor", True)
        ss.record_feedback("editor", False)
        row = ss._load_usage()["editor"]
        self.assertEqual(row["helped"], 2)
        self.assertEqual(row["missed"], 1)

    def test_weight_cold_start(self):
        self.assertEqual(ss._feedback_weight({}), 1.0)

    def test_weight_all_helped_and_bounds(self):
        self.assertEqual(ss._feedback_weight({"helped": 9, "missed": 0}), 1.5)
        self.assertEqual(ss._feedback_weight({"helped": 0, "missed": 9}), 0.5)

    def test_weight_mixed(self):
        w = ss._feedback_weight({"helped": 3, "missed": 1})  # 75% -> 1.25
        self.assertAlmostEqual(w, 1.25, places=2)


class SemanticTests(_Base):
    def _seed(self):
        ss.upsert_skill("Editor", "copy editor", "tidy prose", "x")
        ss.upsert_skill("Deployer", "ship to prod", "release the app", "x")

    def test_semantic_ranks_by_cosine(self):
        self._seed()

        # embed_fn: query close to "editor" text, far from "deployer"
        def embed(texts):
            out = []
            for t in texts:
                if "edit" in t.lower() or "prose" in t.lower() or "tidy" in t.lower():
                    out.append([1.0, 0.0])
                else:
                    out.append([0.0, 1.0])
            return out

        res = ss.match_skills_semantic("help me tidy my prose", top_k=2, embed_fn=embed)
        self.assertEqual(res[0]["slug"], "editor")

    def test_feedback_reorders_within_bound(self):
        self._seed()
        # make both equally similar, then give deployer strong positive feedback
        ss.record_feedback("deployer", True)
        ss.record_feedback("deployer", True)
        ss.record_feedback("editor", False)
        ss.record_feedback("editor", False)

        def embed(texts):
            return [[1.0, 0.0] for _ in texts]  # identical -> cosine equal

        res = ss.match_skills_semantic("anything", top_k=2, embed_fn=embed)
        self.assertEqual(res[0]["slug"], "deployer")

    def test_fallback_when_no_embeddings(self):
        self._seed()
        res = ss.match_skills_semantic("copy editor prose", top_k=2, embed_fn=lambda t: None)
        # falls back to token overlap -> editor still surfaces
        self.assertTrue(any(r["slug"] == "editor" for r in res))

    def test_empty_query(self):
        self._seed()
        self.assertEqual(ss.match_skills_semantic("", embed_fn=lambda t: [[1.0]]), [])

    def test_top_k(self):
        for i in range(5):
            ss.upsert_skill(f"Skill{i}", "does things", "when needed", "x")
        res = ss.match_skills_semantic("things", top_k=2, embed_fn=lambda ts: [[1.0] for _ in ts])
        self.assertEqual(len(res), 2)


if __name__ == "__main__":
    unittest.main()
