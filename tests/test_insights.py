"""stage 1e - cross-domain causal insights. tests first (RED)."""

import asyncio
import os
import unittest

from sqlalchemy import create_engine
from sqlalchemy.pool import StaticPool

os.environ["AUTH_ENABLED"] = "false"
import core.database as db
from services import insights


class CoreTests(unittest.TestCase):
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

    def _items(self):
        return self.s.query(db.Insight).all()

    def test_apply_creates_insight_with_evidence(self):
        n = insights.apply_insights(
            self.s,
            [
                {
                    "title": "productive after social events",
                    "body": "...",
                    "kind": "productivity",
                    "evidence": ["habit:gym", "event:dinner"],
                }
            ],
        )
        self.assertEqual(n, 1)
        ins = self._items()[0]
        self.assertEqual(ins.kind, "productivity")
        self.assertIn("habit:gym", ins.evidence)
        self.assertTrue(ins.dedupe_key)

    def test_dedupe_by_evidence_set(self):
        item = {"title": "x", "body": "", "kind": "spending", "evidence": ["a", "b"]}
        insights.apply_insights(self.s, [item])
        insights.apply_insights(
            self.s,
            [{"title": "different title", "body": "", "kind": "spending", "evidence": ["b", "a"]}],
        )
        self.assertEqual(len(self._items()), 1)  # same evidence set (order-independent) -> dedup

    def test_dismissed_not_recreated(self):
        self.s.add(
            db.Insight(
                title="gone",
                dedupe_key=insights._dedupe_key(["k1"]),
                evidence='["k1"]',
                dismissed=True,
            )
        )
        self.s.commit()
        insights.apply_insights(
            self.s, [{"title": "gone", "body": "", "kind": "", "evidence": ["k1"]}]
        )
        live = [i for i in self._items() if not i.dismissed]
        self.assertEqual(len(live), 0)  # suppressed

    def test_generate_async_with_fake_model(self):
        async def fake(corpus):
            return '[{"title": "spending up after price hikes", "body": "y", "kind": "spending", "evidence": ["sub:netflix"]}]'

        res = asyncio.run(insights.generate_async(self.s, model_fn=fake, force=True))
        self.assertTrue(any(i.title == "spending up after price hikes" for i in self._items()))
        self.assertEqual(res["count"], 1)

    def test_generate_gated_off_is_noop(self):
        async def fake(corpus):
            return '[{"title": "should not appear", "body": "", "kind": "", "evidence": ["z"]}]'

        # not force + insights_enabled default False -> no generation
        res = asyncio.run(insights.generate_async(self.s, model_fn=fake, force=False))
        self.assertFalse(res["ran"])
        self.assertEqual(len(self._items()), 0)

    def test_gather_corpus_shape(self):
        self.s.add(db.SignalSnapshot(category="task", key="task:1", urgency=70))
        self.s.add(db.ProactiveOutcome(category="task", outcome="acted"))
        self.s.commit()
        corpus = insights.gather_corpus(self.s)
        self.assertIn("category_prefs", corpus)
        self.assertIn("signal_history", corpus)


class EndpointTests(unittest.TestCase):
    def setUp(self):
        from starlette.testclient import TestClient

        self.eng = create_engine(
            "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
        )
        db.Base.metadata.create_all(self.eng)
        self._orig = db.engine
        db.engine = self.eng
        db.SessionLocal.configure(bind=self.eng)
        from app import app

        self.c = TestClient(app)
        self.s = db.SessionLocal()

    def tearDown(self):
        self.s.close()
        db.SessionLocal.configure(bind=self._orig)
        db.engine = self._orig
        self.eng.dispose()

    def test_list_pinned_first_excludes_dismissed(self):
        self.s.add(db.Insight(title="normal", dedupe_key="d1"))
        self.s.add(db.Insight(title="pinned one", dedupe_key="d2", pinned=True))
        self.s.add(db.Insight(title="hidden", dedupe_key="d3", dismissed=True))
        self.s.commit()
        rows = self.c.get("/api/insights").json()
        titles = [r["title"] for r in rows]
        self.assertEqual(titles[0], "pinned one")  # pinned first
        self.assertNotIn("hidden", titles)

    def test_pin_endpoint(self):
        i = db.Insight(title="pin me", dedupe_key="p1")
        self.s.add(i)
        self.s.commit()
        self.c.post(f"/api/insights/{i.id}/pin")
        self.s.expire_all()
        self.assertTrue(self.s.get(db.Insight, i.id).pinned)

    def test_dismiss_endpoint(self):
        i = db.Insight(title="dismiss me", dedupe_key="x1")
        self.s.add(i)
        self.s.commit()
        self.c.post(f"/api/insights/{i.id}/dismiss")
        self.s.expire_all()
        self.assertTrue(self.s.get(db.Insight, i.id).dismissed)

    def test_setting_default_false(self):
        from core.settings import _defaults

        self.assertFalse(_defaults.get("insights_enabled", True))

    def test_run_endpoint_no_model_is_clean(self):
        r = self.c.post("/api/insights/run")
        self.assertIn("ran", r.json())  # no endpoints -> empty but no error


if __name__ == "__main__":
    unittest.main()
