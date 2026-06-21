import unittest
from unittest import mock

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import core.database as db
from services import memory_store as ms


class MemoryStoreTest(unittest.TestCase):
    def setUp(self):
        self.eng = create_engine(
            "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
        )
        db.Base.metadata.create_all(self.eng)
        self._p = mock.patch.object(ms, "SessionLocal", sessionmaker(bind=self.eng))
        self._p.start()

    def tearDown(self):
        self._p.stop()
        self.eng.dispose()

    def test_detect_category(self):
        self.assertEqual(ms._detect_category("I am Bob and I work at Acme"), "identity")
        self.assertEqual(ms._detect_category("i like strong coffee"), "preference")
        self.assertEqual(ms._detect_category("remind me to call the dentist"), "task")
        self.assertEqual(ms._detect_category("the sky is blue"), "general")

    def test_add_get_delete(self):
        m = ms.add_memory("I am a teacher")
        self.assertEqual(m["category"], "identity")  # auto-detected
        self.assertEqual([x["id"] for x in ms.get_all_memories()], [m["id"]])
        self.assertTrue(ms.delete_memory(m["id"]))
        self.assertEqual(ms.get_all_memories(), [])
        self.assertFalse(ms.delete_memory("nope"))

    def test_update(self):
        m = ms.add_memory("draft", category="general")
        upd = ms.update_memory(m["id"], text="final", pinned=True)
        self.assertEqual(upd["text"], "final")
        self.assertTrue(upd["pinned"])
        self.assertIsNone(ms.update_memory("nope", text="x"))

    def test_search_ranks_relevant_and_pins_first(self):
        ms.add_memory("I love hiking in the mountains")  # preference
        ms.add_memory("the weather is cold today")  # general
        ms.add_memory("always remember this", pinned=True)
        res = [r["text"] for r in ms.search_memories("what do I like to do")]
        self.assertEqual(res[0], "always remember this")  # pinned first regardless of score
        self.assertLess(
            res.index("I love hiking in the mountains"), res.index("the weather is cold today")
        )  # more relevant ranks higher

    def test_debug_search_exposes_scores_and_method(self):
        ms.add_memory("I love hiking in the mountains")
        ms.add_memory("the weather is cold today")
        ms.add_memory("always remember this", pinned=True)
        out = ms.debug_search("what do I like to do")
        self.assertIn(out["method"], ("vector", "jaccard"))
        self.assertEqual(out["results"][0]["pinned"], True)  # pinned listed first
        # every row carries a score + base + boost breakdown
        for r in out["results"]:
            self.assertIn("score", r)
            self.assertIn("base", r)
            self.assertIn("boost", r)
        # the relevant one outscores the irrelevant one among the non-pinned
        rest = {r["text"]: r["score"] for r in out["results"] if not r["pinned"]}
        self.assertGreater(rest["I love hiking in the mountains"], rest["the weather is cold today"])

    def test_debug_search_empty(self):
        self.assertEqual(ms.debug_search("anything")["results"], [])

    def test_inject_memories_builds_prompt(self):
        ms.add_memory("I am vegetarian")
        out = ms.inject_memories("what should I cook")
        self.assertIn("Relevant things you know about the user", out)
        self.assertIn("I am vegetarian", out)
        # nothing stored that matches → empty
        ms.delete_memory(ms.get_all_memories()[0]["id"])
        self.assertEqual(ms.inject_memories("anything"), "")

    def test_detect_category_contact(self):
        self.assertEqual(ms._detect_category("my email is test@example.com"), "contact")

    def test_add_with_explicit_category(self):
        m = ms.add_memory("some random text", category="preference")
        self.assertEqual(m["category"], "preference")

    def test_pinned_flag_stored(self):
        m = ms.add_memory("sticky note", pinned=True)
        self.assertTrue(m["pinned"])
        all_m = ms.get_all_memories()
        self.assertTrue(all_m[0]["pinned"])

    def test_update_category_only(self):
        m = ms.add_memory("I work at ACME", category="identity")
        upd = ms.update_memory(m["id"], category="contact")
        self.assertEqual(upd["category"], "contact")
        # text unchanged
        self.assertEqual(upd["text"], "I work at ACME")

    def test_search_empty_index_returns_empty(self):
        self.assertEqual(ms.search_memories("anything"), [])

    def test_multiple_pinned_all_appear_first(self):
        ms.add_memory("pinned A", pinned=True)
        ms.add_memory("pinned B", pinned=True)
        ms.add_memory("regular C")
        results = ms.search_memories("something about C")
        pinned_texts = [r["text"] for r in results if r["pinned"]]
        # both pinned appear before regular ones
        first_non_pinned = next((i for i, r in enumerate(results) if not r["pinned"]), len(results))
        for i, r in enumerate(results):
            if r["pinned"]:
                self.assertLess(i, first_non_pinned)
        self.assertEqual(len(pinned_texts), 2)


if __name__ == "__main__":
    unittest.main()
