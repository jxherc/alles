"""stage 3g - deep_research fact cache + dedup + contradictions. tests first (RED)."""

import os
import unittest

from sqlalchemy import create_engine
from sqlalchemy.pool import StaticPool

os.environ["AUTH_ENABLED"] = "false"
import core.database as db
from services.research import fact_cache as fc


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

    def tearDown(self):
        self.s.close()
        db.SessionLocal.configure(bind=self._orig)
        db.engine = self._orig
        self.eng.dispose()


class DedupeTests(unittest.TestCase):
    def test_dedupe_by_normalized_url(self):
        f = [
            {"url": "https://x.com/a", "summary": "1"},
            {"url": "https://x.com/a/", "summary": "2"},  # trailing slash
            {"url": "https://x.com/a#sec", "summary": "3"},  # fragment
            {"url": "https://x.com/b", "summary": "4"},
        ]
        out = fc.dedupe(f)
        self.assertEqual(len(out), 2)

    def test_norm_url(self):
        self.assertEqual(fc._norm_url("https://X.com/p/#frag"), fc._norm_url("https://x.com/p"))


class StoreTests(_Base):
    def test_store_inserts(self):
        n = fc.store(self.s, [{"url": "https://x.com/a", "summary": "s", "title": "t"}], "q1")
        self.assertEqual(n, 1)
        self.assertEqual(self.s.query(db.ResearchFinding).count(), 1)

    def test_store_skips_existing_url(self):
        fc.store(self.s, [{"url": "https://x.com/a", "summary": "s"}], "q1")
        n = fc.store(self.s, [{"url": "https://x.com/a", "summary": "s2"}], "q2")
        self.assertEqual(n, 0)  # url already cached
        self.assertEqual(self.s.query(db.ResearchFinding).count(), 1)

    def test_store_dedupes_within_batch(self):
        n = fc.store(
            self.s,
            [{"url": "https://x.com/a"}, {"url": "https://x.com/a/"}, {"url": "https://x.com/b"}],
            "q",
        )
        self.assertEqual(n, 2)

    def test_cached_overlap(self):
        fc.store(
            self.s,
            [{"url": "https://x.com/a", "summary": "rust async runtime"}],
            "how does rust async work",
        )
        hits = fc.cached(self.s, "rust async question")
        self.assertTrue(any("x.com/a" in h["url"] for h in hits))

    def test_cached_no_overlap_empty(self):
        fc.store(self.s, [{"url": "https://x.com/a"}], "cooking pasta")
        self.assertEqual(fc.cached(self.s, "quantum chromodynamics"), [])


class ContradictionTests(unittest.TestCase):
    def test_flags_opposite_polarity_same_topic(self):
        f = [
            {"url": "a", "summary": "The vaccine reduces hospitalization significantly in adults."},
            {
                "url": "b",
                "summary": "The vaccine does not reduce hospitalization significantly in adults.",
            },
        ]
        c = fc.contradictions(f)
        self.assertEqual(len(c), 1)
        self.assertEqual({c[0]["a"], c[0]["b"]}, {"a", "b"})

    def test_ignores_same_polarity(self):
        f = [
            {"url": "a", "summary": "The vaccine reduces hospitalization significantly in adults."},
            {
                "url": "b",
                "summary": "The vaccine reduces hospitalization clearly among adults too.",
            },
        ]
        self.assertEqual(fc.contradictions(f), [])

    def test_ignores_unrelated(self):
        f = [
            {"url": "a", "summary": "Cats are not nocturnal animals usually."},
            {"url": "b", "summary": "The stock market rallied strongly today afternoon."},
        ]
        self.assertEqual(fc.contradictions(f), [])


if __name__ == "__main__":
    unittest.main()
