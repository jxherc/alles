"""stage 1f - intent prediction + contextual suggestions. tests first (RED)."""

import datetime
import os
import unittest

from sqlalchemy import create_engine
from sqlalchemy.pool import StaticPool

os.environ["AUTH_ENABLED"] = "false"
import core.database as db
from services import intent


class PredictTests(unittest.TestCase):
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

    def _labels(self, **kw):
        return [c["label"] for c in intent.predict_suggestions(self.s, **kw)]

    def test_overdue_task_suggestion(self):
        self.s.add(db.Task(title="file taxes", due_date="2020-01-01", done=False))
        self.s.commit()
        self.assertTrue(any("overdue" in label for label in self._labels(limit=4)))

    def test_sub_renewal_suggestion(self):
        soon = (datetime.date.today() + datetime.timedelta(days=2)).isoformat()
        self.s.add(db.Subscription(name="netflix", active=True, next_due=soon, price=10))
        self.s.commit()
        self.assertTrue(any("renewal" in label for label in self._labels(limit=4)))

    def test_budget_message_suggestion(self):
        labels = self._labels(message="how much did i spend on groceries", limit=4)
        self.assertTrue(any("spending" in label for label in labels))

    def test_travel_message_suggestion(self):
        labels = self._labels(message="i'm planning a trip to japan", limit=4)
        self.assertTrue(any("trip" in label for label in labels))

    def test_travel_event_suggestion(self):
        today = datetime.date.today().isoformat()
        self.s.add(db.CalendarEvent(title="flight to tokyo", start_dt=today, all_day=True))
        self.s.commit()
        labels = self._labels(limit=4)
        self.assertTrue(any("tokyo" in label.lower() or "trip" in label for label in labels))

    def test_limit_respected(self):
        self.s.add(db.Task(title="t", due_date="2020-01-01", done=False))
        soon = (datetime.date.today() + datetime.timedelta(days=2)).isoformat()
        self.s.add(db.Subscription(name="x", active=True, next_due=soon, price=1))
        self.s.commit()
        out = intent.predict_suggestions(self.s, message="spend budget trip", limit=2)
        self.assertLessEqual(len(out), 2)

    def test_empty_returns_nothing(self):
        self.assertEqual(intent.predict_suggestions(self.s, message="", limit=2), [])

    def test_dedupe_no_repeat_labels(self):
        labels = self._labels(message="trip travel flight vacation", limit=4)
        self.assertEqual(len(labels), len(set(labels)))


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

    def test_endpoint_returns_suggestions(self):
        self.s.add(db.Task(title="pay rent", due_date="2020-01-01", done=False))
        self.s.commit()
        r = self.c.get("/api/aide/suggestions").json()
        self.assertTrue(any("overdue" in x["label"] for x in r))

    def test_endpoint_with_message(self):
        r = self.c.get("/api/aide/suggestions?q=show me my budget").json()
        self.assertTrue(any("spending" in x["label"] for x in r))

    def test_setting_default_on(self):
        from core.settings import _defaults

        self.assertTrue(_defaults.get("intent_suggestions", False))


if __name__ == "__main__":
    unittest.main()
