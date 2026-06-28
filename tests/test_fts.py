"""stage 3i - FTS5 first-class store. tests first (RED)."""

import os
import unittest

from sqlalchemy import create_engine
from sqlalchemy.pool import StaticPool

os.environ["AUTH_ENABLED"] = "false"
import core.database as db
from services import fts


class _Base(unittest.TestCase):
    def setUp(self):
        self.eng = create_engine(
            "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
        )
        db.Base.metadata.create_all(self.eng)
        self._orig = db.engine
        db.engine = self.eng
        db.SessionLocal.configure(bind=self.eng)
        self.s = db.SessionLocal()
        fts.ensure(self.s)

    def tearDown(self):
        self.s.close()
        db.SessionLocal.configure(bind=self._orig)
        db.engine = self._orig
        self.eng.dispose()

    def _refs(self, results):
        return [r["ref"] for r in results]


class SearchTests(_Base):
    def test_index_and_find(self):
        fts.index(self.s, "note", "n1", "the quick brown fox jumps")
        self.assertIn("n1", self._refs(fts.search(self.s, "fox")))

    def test_phrase_match_only(self):
        fts.index(self.s, "note", "n1", "the quick brown fox")
        fts.index(self.s, "note", "n2", "quick fox brown the")  # words present but not adjacent
        res = self._refs(fts.search(self.s, '"quick brown"'))
        self.assertIn("n1", res)
        self.assertNotIn("n2", res)

    def test_negation(self):
        fts.index(self.s, "note", "n1", "cats and dogs")
        fts.index(self.s, "note", "n2", "cats and birds")
        res = self._refs(fts.search(self.s, "cats NOT dogs"))
        self.assertEqual(res, ["n2"])

    def test_prefix(self):
        fts.index(self.s, "note", "n1", "jumping high")  # porter keeps the 'jump' prefix
        self.assertIn("n1", self._refs(fts.search(self.s, "jump*")))

    def test_title_outranks_body(self):
        fts.index(self.s, "note", "body", "a long body that mentions python once", title="cooking")
        fts.index(self.s, "note", "title", "unrelated filler text here entirely", title="python")
        res = self._refs(fts.search(self.s, "python"))
        self.assertEqual(res[0], "title")  # title hit ranks first

    def test_kind_filter(self):
        fts.index(self.s, "note", "n1", "shared word")
        fts.index(self.s, "mail", "m1", "shared word")
        res = self._refs(fts.search(self.s, "shared", kind="mail"))
        self.assertEqual(res, ["m1"])

    def test_reindex_replaces(self):
        fts.index(self.s, "note", "n1", "first version apple")
        fts.index(self.s, "note", "n1", "second version banana")
        self.assertEqual(self._refs(fts.search(self.s, "apple")), [])
        self.assertIn("n1", self._refs(fts.search(self.s, "banana")))

    def test_remove(self):
        fts.index(self.s, "note", "n1", "removable content")
        fts.remove(self.s, "note", "n1")
        self.assertEqual(fts.search(self.s, "removable"), [])

    def test_no_match_empty(self):
        fts.index(self.s, "note", "n1", "something")
        self.assertEqual(fts.search(self.s, "nothingmatcheshere"), [])

    def test_porter_stemming(self):
        fts.index(self.s, "note", "n1", "she was running")
        self.assertIn("n1", self._refs(fts.search(self.s, "run")))

    def test_on_mutation_indexes(self):
        fts.on_mutation(self.s, "task", "t1", "buy milk and eggs")
        self.assertIn("t1", self._refs(fts.search(self.s, "milk")))

    def test_malformed_query_safe(self):
        fts.index(self.s, "note", "n1", "safe content")
        # various fts5 syntax errors must degrade to [] instead of raising
        for bad in ['"unbalanced', "AND", "NEAR(", "badcol:term", "*"]:
            self.assertIsInstance(fts.search(self.s, bad), list, bad)

    def test_session_recovers_after_malformed_query(self):
        # contract: a malformed search leaves the session fully usable — later reads AND writes
        # still work (the except path rolls back defensively to guarantee this).
        fts.index(self.s, "note", "n1", "the quick brown fox")
        fts.search(self.s, '"unbalanced')          # poisons + should self-heal
        self.assertEqual(self._refs(fts.search(self.s, "fox")), ["n1"])  # valid search still works
        fts.index(self.s, "note", "n2", "another fox")                   # writes still work too
        self.assertEqual(set(self._refs(fts.search(self.s, "fox"))), {"n1", "n2"})


if __name__ == "__main__":
    unittest.main()
