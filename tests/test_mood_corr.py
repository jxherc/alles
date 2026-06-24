"""4b - mood<->behavior correlations: scoring, Spearman, and the end-to-end builder."""

import tempfile
import unittest
from datetime import date, timedelta
from pathlib import Path
from unittest import mock

from sqlalchemy import create_engine
from sqlalchemy.pool import StaticPool

import core.database as db
import core.settings as cs
from services import mood_corr as mc
from tests._client import ApiTest


class ScoreAndStatTests(unittest.TestCase):
    def test_picker_emoji_scored(self):
        self.assertEqual(mc.mood_score("😄"), 5)
        self.assertEqual(mc.mood_score("😐"), 3)
        self.assertEqual(mc.mood_score("😢"), 1)

    def test_words_scored(self):
        self.assertEqual(mc.mood_score("great"), 5)
        self.assertEqual(mc.mood_score("Stressed"), 2)
        self.assertEqual(mc.mood_score("felt ok today"), 3)  # token match

    def test_unknown_is_none(self):
        self.assertIsNone(mc.mood_score(""))
        self.assertIsNone(mc.mood_score("zxcv"))

    def test_spearman_perfect(self):
        self.assertAlmostEqual(mc.spearman([1, 2, 3, 4], [10, 20, 30, 40]), 1.0, places=6)
        self.assertAlmostEqual(mc.spearman([1, 2, 3, 4], [40, 30, 20, 10]), -1.0, places=6)

    def test_spearman_no_variance_none(self):
        self.assertIsNone(mc.spearman([1, 1, 1, 1], [1, 2, 3, 4]))

    def test_spearman_too_few_none(self):
        self.assertIsNone(mc.spearman([1, 2], [1, 2]))


class BuilderTests(unittest.TestCase):
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

    def _day(self, n):
        return (date.today() - timedelta(days=n)).isoformat()

    def _journal(self, n, mood):
        self.s.add(db.JournalEntry(date=self._day(n), content="x", mood=mood))

    def test_not_enough_mood(self):
        for i in range(3):
            self._journal(i, "🙂")
        self.s.commit()
        out = mc.correlations(self.s, min_overlap=6)
        self.assertFalse(out["ok"])
        self.assertEqual(out["correlations"], [])

    def test_habit_positive_correlation(self):
        h = db.Habit(name="run")
        self.s.add(h)
        self.s.commit()
        # high mood on the days the habit was done, low mood when not
        for i in range(8):
            good = i % 2 == 0
            self._journal(i, "😄" if good else "😢")
            if good:
                self.s.add(db.HabitLog(habit_id=h.id, date=self._day(i)))
        self.s.commit()
        out = mc.correlations(self.s, min_overlap=6)
        self.assertTrue(out["ok"])
        run = next(c for c in out["correlations"] if c["label"] == "habit:run")
        self.assertGreater(run["rho"], 0.5)
        self.assertIn("run", run["explain"])

    def test_health_metric_correlation(self):
        # more sleep -> better mood
        for i in range(8):
            self._journal(i, "😄" if i < 4 else "😢")
            self.s.add(db.HealthEntry(kind="sleep", date=self._day(i), value=(9 if i < 4 else 4)))
        self.s.commit()
        out = mc.correlations(self.s, min_overlap=6)
        sleep = next(c for c in out["correlations"] if c["label"] == "health:sleep")
        self.assertGreater(sleep["rho"], 0.5)

    def test_tasks_completed_correlation(self):
        import datetime as _dt

        # finish tasks on good-mood days, none on bad-mood days -> positive link
        for i in range(8):
            good = i < 4
            self._journal(i, "😄" if good else "😢")
            if good:
                self.s.add(db.Task(title=f"t{i}", done=True, completed_at=_dt.datetime.combine(
                    _dt.date.fromisoformat(self._day(i)), _dt.time(12, 0))))
        self.s.commit()
        out = mc.correlations(self.s, min_overlap=6)
        tc = next(c for c in out["correlations"] if c["label"] == "tasks completed")
        self.assertGreater(tc["rho"], 0.4)
        self.assertIn("tasks completed", tc["explain"])

    def test_archived_habit_excluded(self):
        h = db.Habit(name="old", archived=True)
        self.s.add(h)
        self.s.commit()
        for i in range(8):
            self._journal(i, "🙂")
            self.s.add(db.HabitLog(habit_id=h.id, date=self._day(i)))
        self.s.commit()
        out = mc.correlations(self.s, min_overlap=6)
        self.assertFalse(any(c["label"] == "habit:old" for c in out["correlations"]))


class RouteTests(ApiTest):
    def setUp(self):
        super().setUp()
        self.tmp = tempfile.TemporaryDirectory()
        self.sp = mock.patch.object(cs, "_SETTINGS_FILE", Path(self.tmp.name) / "settings.json")
        self.sp.start()
        import routes.journal as j

        j._unlock_tokens.clear()

    def tearDown(self):
        self.sp.stop()
        self.tmp.cleanup()
        super().tearDown()

    def test_route_open_shape(self):
        r = self.client.get("/api/journal/mood-correlations")
        self.assertEqual(r.status_code, 200)
        self.assertIn("correlations", r.json())

    def test_route_locked_403(self):
        self.client.post("/api/journal/lock/set", json={"passcode": "1234"})
        self.assertEqual(self.client.get("/api/journal/mood-correlations").status_code, 403)

    def test_route_unlocked_with_token(self):
        self.client.post("/api/journal/lock/set", json={"passcode": "1234"})
        tok = self.client.post("/api/journal/unlock", json={"passcode": "1234"}).json()["token"]
        r = self.client.get("/api/journal/mood-correlations", headers={"X-Journal-Token": tok})
        self.assertEqual(r.status_code, 200)


if __name__ == "__main__":
    unittest.main()
