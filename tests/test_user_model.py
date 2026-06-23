"""stage 1c - memory auto-distillation. tests first (RED)."""

import asyncio
import os
import unittest

from sqlalchemy import create_engine, text
from sqlalchemy.pool import StaticPool

os.environ["AUTH_ENABLED"] = "false"
import core.database as db
from services import user_model


class MigrationTests(unittest.TestCase):
    def test_m0002_shape(self):
        from core.migrations import m0002_memory_distill as m

        self.assertEqual(m.VERSION, 2)
        self.assertTrue(callable(m.up))

    def test_m0002_adds_columns_to_stripped_table(self):
        eng = create_engine("sqlite://", poolclass=StaticPool)
        from core.migrations import m0002_memory_distill as m

        with eng.begin() as c:
            c.execute(text("CREATE TABLE memories (id TEXT PRIMARY KEY, text TEXT)"))
            m.up(c)
            cols = {r[1] for r in c.execute(text("PRAGMA table_info(memories)"))}
        self.assertTrue({"confidence", "vetoed", "provenance"} <= cols)
        eng.dispose()


class DistillCoreTests(unittest.TestCase):
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

    def _distilled(self):
        return self.s.query(db.Memory).filter(db.Memory.source == "distilled").all()

    def test_apply_distilled_creates_fact(self):
        n = user_model.apply_distilled(
            self.s,
            [
                {
                    "text": "batches research before deciding",
                    "category": "preference",
                    "confidence": 0.7,
                }
            ],
            provenance="sessions:5",
        )
        self.assertEqual(n, 1)
        m = self._distilled()[0]
        self.assertEqual(m.source, "distilled")
        self.assertAlmostEqual(m.confidence, 0.7)
        self.assertEqual(m.provenance, "sessions:5")

    def test_apply_distilled_dedupes_by_text(self):
        f = [{"text": "prefers short summaries", "category": "preference", "confidence": 0.6}]
        user_model.apply_distilled(self.s, f)
        user_model.apply_distilled(self.s, f)
        self.assertEqual(len(self._distilled()), 1)

    def test_apply_distilled_skips_vetoed_text(self):
        self.s.add(db.Memory(text="no nagging reminders", source="distilled", vetoed=True))
        self.s.commit()
        user_model.apply_distilled(
            self.s, [{"text": "no nagging reminders", "category": "preference", "confidence": 0.9}]
        )
        # still just the one vetoed row, not re-created
        self.assertEqual(len(self._distilled()), 1)
        self.assertTrue(self._distilled()[0].vetoed)

    def test_decay_lowers_confidence(self):
        user_model.apply_distilled(
            self.s, [{"text": "likes automation", "category": "preference", "confidence": 1.0}]
        )
        user_model.decay(self.s, factor=0.8)
        self.assertAlmostEqual(self._distilled()[0].confidence, 0.8)

    def test_decay_drops_faded_keeps_pinned(self):
        user_model.apply_distilled(
            self.s, [{"text": "faint", "category": "general", "confidence": 0.3}]
        )
        user_model.apply_distilled(
            self.s, [{"text": "kept", "category": "general", "confidence": 0.3}]
        )
        kept = self.s.query(db.Memory).filter(db.Memory.text == "kept").first()
        kept.pinned = True
        self.s.commit()
        dropped = user_model.decay(self.s, factor=0.5, floor=0.25)  # 0.3*0.5=0.15 < 0.25
        self.assertEqual(dropped, 1)
        texts = {m.text for m in self._distilled()}
        self.assertIn("kept", texts)
        self.assertNotIn("faint", texts)

    def test_veto_hides_and_excludes_from_search(self):
        from services import memory_store

        m = (
            user_model.apply_distilled(
                self.s, [{"text": "secret pref", "category": "preference", "confidence": 0.9}]
            )
            and self._distilled()[0]
        )
        ok = user_model.veto(self.s, m.id)
        self.assertTrue(ok)
        self.assertTrue(self.s.get(db.Memory, m.id).vetoed)
        # excluded from search
        results = memory_store.search_memories("secret pref", top_k=6)
        self.assertFalse(any(r["text"] == "secret pref" for r in results))

    def test_gather_evidence_from_sessions_and_outcomes(self):
        self.s.add(db.Session(name="planning the trip"))
        self.s.add(db.Session(name="debugging the build"))
        self.s.add(db.ProactiveOutcome(category="task", outcome="acted"))
        self.s.add(db.ProactiveOutcome(category="sub", outcome="dismissed"))
        self.s.commit()
        ev = user_model.gather_evidence(self.s)
        self.assertTrue(any("trip" in t for t in ev["topics"]))
        self.assertIn("task", ev["category_prefs"])

    def test_distill_async_with_fake_model(self):
        async def fake_model(evidence):
            return '[{"text": "works late", "category": "fact", "confidence": 0.8}]'

        asyncio.run(user_model.distill_async(self.s, model_fn=fake_model))
        self.assertTrue(any(m.text == "works late" for m in self._distilled()))


class RoutesAndInjectionTests(unittest.TestCase):
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

    def test_distilled_list_endpoint(self):
        self.s.add(db.Memory(text="distilled one", source="distilled", confidence=0.7))
        self.s.add(db.Memory(text="manual one", source="manual"))
        self.s.commit()
        r = self.c.get("/api/memory/distilled").json()
        texts = {m["text"] for m in r}
        self.assertIn("distilled one", texts)
        self.assertNotIn("manual one", texts)

    def test_veto_endpoint_hides_fact(self):
        m = db.Memory(text="veto me", source="distilled", confidence=0.8)
        self.s.add(m)
        self.s.commit()
        self.c.post(f"/api/memory/{m.id}/veto")
        self.s.expire_all()
        self.assertTrue(self.s.get(db.Memory, m.id).vetoed)

    def test_setting_default_false(self):
        from core.settings import _defaults

        self.assertFalse(_defaults.get("user_model_distill", True))

    def test_inject_includes_distilled_excludes_vetoed(self):
        from services import memory_store

        self.s.add(db.Memory(text="prefers dark mode always", source="distilled", confidence=0.9))
        self.s.add(db.Memory(text="hidden vetoed fact zzz", source="distilled", vetoed=True))
        self.s.commit()
        out = memory_store.inject_memories("what theme do i like", top_k=6)
        self.assertIn("dark mode", out)
        self.assertNotIn("zzz", out)


if __name__ == "__main__":
    unittest.main()
