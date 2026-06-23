"""stage 1a - proactive feedback loop. tests first (RED)."""

import os
import unittest

from sqlalchemy import create_engine
from sqlalchemy.pool import StaticPool

os.environ["AUTH_ENABLED"] = "false"
import core.database as db
from services import proactive


def _card(db_, key="task_overdue:1", category="task", score=80):
    it = db.ProactiveItem(
        dedupe_key=proactive._dedupe_key([key]),
        category=category,
        title="t",
        body="",
        link="tasks",
        score=score,
        urgency=70,
        source_keys=f'["{key}"]',
    )
    db_.add(it)
    db_.commit()
    return it


class FeedbackUnitTests(unittest.TestCase):
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

    def _outcomes(self, outcome=None):
        q = self.s.query(db.ProactiveOutcome)
        if outcome:
            q = q.filter(db.ProactiveOutcome.outcome == outcome)
        return q.all()

    def test_record_outcome_writes_row_with_latency(self):
        it = _card(self.s)
        proactive.record_outcome(self.s, it, "acted")
        rows = self._outcomes("acted")
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0].item_id, it.id)
        self.assertEqual(rows[0].category, "task")
        self.assertGreaterEqual(rows[0].latency_sec, 0.0)

    def test_cold_start_weight_is_neutral(self):
        self.assertEqual(proactive._category_weight(self.s, "task"), 1.0)

    def test_dismisses_drive_weight_down(self):
        for _ in range(8):
            o = db.ProactiveOutcome(category="sub", outcome="dismissed")
            self.s.add(o)
        self.s.commit()
        w = proactive._category_weight(self.s, "sub")
        self.assertLess(w, 1.0)
        self.assertGreaterEqual(w, 0.5)

    def test_acts_drive_weight_up(self):
        for _ in range(8):
            self.s.add(db.ProactiveOutcome(category="task", outcome="acted"))
        self.s.commit()
        w = proactive._category_weight(self.s, "task")
        self.assertGreater(w, 1.0)
        self.assertLessEqual(w, 1.5)

    def test_weight_is_bounded(self):
        for _ in range(200):
            self.s.add(db.ProactiveOutcome(category="x", outcome="dismissed"))
        for _ in range(200):
            self.s.add(db.ProactiveOutcome(category="y", outcome="acted"))
        self.s.commit()
        self.assertGreaterEqual(proactive._category_weight(self.s, "x"), 0.5)
        self.assertLessEqual(proactive._category_weight(self.s, "y"), 1.5)

    def test_upsert_applies_weight(self):
        # cold start: score unchanged from base
        sigs = [{"key": "task_overdue:1", "urgency": 70, "category": "task"}]
        cards = [
            {
                "source_keys": ["task_overdue:1"],
                "score": 80,
                "title": "t",
                "body": "",
                "link": "tasks",
            }
        ]
        proactive._upsert(self.s, cards, sigs)
        it = self.s.query(db.ProactiveItem).filter_by(category="task").first()
        self.assertEqual(it.score, 80)

    def test_upsert_penalizes_dismissed_category(self):
        for _ in range(10):
            self.s.add(db.ProactiveOutcome(category="sub", outcome="dismissed"))
        self.s.commit()
        sigs = [{"key": "sub_renew:9:2026-07-01", "urgency": 65, "category": "sub"}]
        cards = [
            {
                "source_keys": ["sub_renew:9:2026-07-01"],
                "score": 80,
                "title": "t",
                "body": "",
                "link": "subs",
            }
        ]
        proactive._upsert(self.s, cards, sigs)
        it = self.s.query(db.ProactiveItem).filter_by(category="sub").first()
        self.assertLess(it.score, 80)  # learned weight pulled it down

    def test_prune_records_ignored(self):
        _card(self.s, key="task_overdue:1", category="task")
        # signal gone -> prune should record an 'ignored' outcome then delete the card
        proactive._prune_resolved(self.s, sigs=[])
        ign = self._outcomes("ignored")
        self.assertEqual(len(ign), 1)
        self.assertEqual(ign[0].category, "task")
        self.assertEqual(self.s.query(db.ProactiveItem).count(), 0)  # still deleted

    def test_feedback_stats_per_category(self):
        self.s.add(db.ProactiveOutcome(category="task", outcome="acted"))
        self.s.add(db.ProactiveOutcome(category="task", outcome="dismissed"))
        self.s.add(db.ProactiveOutcome(category="sub", outcome="ignored"))
        self.s.commit()
        stats = proactive.feedback_stats(self.s)
        self.assertEqual(stats["task"]["acted"], 1)
        self.assertEqual(stats["task"]["dismissed"], 1)
        self.assertAlmostEqual(stats["task"]["act_rate"], 0.5)
        self.assertIn("weight", stats["task"])
        self.assertEqual(stats["sub"]["ignored"], 1)


class FeedbackEndpointTests(unittest.TestCase):
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

    def test_act_endpoint_marks_acted_and_records(self):
        it = _card(self.s)
        r = self.c.post(f"/api/proactive/{it.id}/act")
        self.assertEqual(r.json(), {"ok": True})
        self.s.expire_all()
        got = self.s.get(db.ProactiveItem, it.id)
        self.assertEqual(got.status, "acted")
        self.assertTrue(got.dismissed)  # leaves the feed
        outs = self.s.query(db.ProactiveOutcome).filter_by(outcome="acted").all()
        self.assertEqual(len(outs), 1)

    def test_dismiss_endpoint_records_outcome(self):
        it = _card(self.s)
        self.c.post(f"/api/proactive/{it.id}/dismiss")
        outs = self.s.query(db.ProactiveOutcome).filter_by(outcome="dismissed").all()
        self.assertEqual(len(outs), 1)

    def test_act_missing_id_returns_false(self):
        r = self.c.post("/api/proactive/nope/act")
        self.assertEqual(r.json(), {"ok": False})

    def test_stats_endpoint(self):
        self.s.add(db.ProactiveOutcome(category="task", outcome="acted"))
        self.s.commit()
        r = self.c.get("/api/proactive/stats").json()
        self.assertEqual(r["task"]["acted"], 1)


if __name__ == "__main__":
    unittest.main()
