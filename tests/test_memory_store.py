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

    def test_inject_memories_builds_prompt(self):
        ms.add_memory("I am vegetarian")
        out = ms.inject_memories("what should I cook")
        self.assertIn("Relevant things you know about the user", out)
        self.assertIn("I am vegetarian", out)
        # nothing stored that matches → empty
        ms.delete_memory(ms.get_all_memories()[0]["id"])
        self.assertEqual(ms.inject_memories("anything"), "")


if __name__ == "__main__":
    unittest.main()
