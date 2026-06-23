"""stage 1b - signal history + cross-domain synthesis. tests first (RED)."""

import datetime
import os
import unittest

from sqlalchemy import create_engine
from sqlalchemy.pool import StaticPool

os.environ["AUTH_ENABLED"] = "false"
import core.database as db
from services import signals


def _sig(category, key, urgency=50):
    return {
        "category": category,
        "key": key,
        "urgency": urgency,
        "title": key,
        "detail": "",
        "link": category,
        "data": {},
    }


class SnapshotTests(unittest.TestCase):
    def setUp(self):
        self.eng = create_engine(
            "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
        )
        db.Base.metadata.create_all(self.eng)
        self._orig = db.engine
        db.engine = self.eng
        db.SessionLocal.configure(bind=self.eng)
        self.s = db.SessionLocal()
        self.now = datetime.datetime(2026, 6, 23, 12, 0, 0)

    def tearDown(self):
        self.s.close()
        db.SessionLocal.configure(bind=self._orig)
        db.engine = self._orig
        self.eng.dispose()

    def _snap(self, days_ago, category, count):
        """seed `count` signal-snapshot rows for one category at one snapshot time."""
        ts = self.now - datetime.timedelta(days=days_ago)
        for i in range(count):
            self.s.add(
                db.SignalSnapshot(
                    ts=ts, category=category, key=f"{category}:{days_ago}:{i}", urgency=50
                )
            )
        self.s.commit()

    def test_record_snapshot_writes_row_per_signal(self):
        sigs = [
            _sig("task", "task_overdue:1"),
            _sig("sub", "sub_renew:2"),
            _sig("task", "task_overdue:3"),
        ]
        n = signals.record_snapshot(self.s, sigs)
        self.assertEqual(n, 3)
        rows = self.s.query(db.SignalSnapshot).all()
        self.assertEqual(len(rows), 3)
        cats = sorted(r.category for r in rows)
        self.assertEqual(cats, ["sub", "task", "task"])

    def test_record_snapshot_trims_old_rows(self):
        old = db.SignalSnapshot(ts=self.now - datetime.timedelta(days=99), category="task", key="x")
        self.s.add(old)
        self.s.commit()
        signals.record_snapshot(
            self.s, [_sig("task", "task_overdue:1")], keep_days=30, now=self.now
        )
        kinds = self.s.query(db.SignalSnapshot).all()
        self.assertEqual(len(kinds), 1)  # the 99-day-old row was trimmed

    def test_synthesize_empty_history(self):
        self.assertEqual(signals.synthesize(self.s, now=self.now), [])

    def test_rising_count_emits_trend(self):
        for d, c in [(6, 1), (4, 2), (2, 4), (0, 6)]:
            self._snap(d, "task", c)
        out = signals.synthesize(self.s, now=self.now)
        trends = [x for x in out if x["key"] == "trend:task"]
        self.assertEqual(len(trends), 1)
        self.assertEqual(trends[0]["category"], "trend")

    def test_trend_carries_explain_and_positive_delta(self):
        for d, c in [(6, 1), (4, 2), (2, 4), (0, 6)]:
            self._snap(d, "task", c)
        t = next(x for x in signals.synthesize(self.s, now=self.now) if x["key"] == "trend:task")
        self.assertIn("explain", t)
        self.assertTrue(t["explain"])
        self.assertGreater(t["data"]["delta"], 0)

    def test_flat_count_no_trend(self):
        for d in (6, 4, 2, 0):
            self._snap(d, "task", 3)
        out = signals.synthesize(self.s, now=self.now)
        self.assertFalse([x for x in out if x["key"] == "trend:task"])

    def test_declining_count_no_trend(self):
        for d, c in [(6, 6), (4, 4), (2, 2), (0, 1)]:
            self._snap(d, "task", c)
        out = signals.synthesize(self.s, now=self.now)
        self.assertFalse([x for x in out if x["key"] == "trend:task"])

    def test_cooccurrence_emits_corr_with_sorted_key(self):
        for d in (4, 2, 0):
            self._snap(d, "task", 1)
            self._snap(d, "budget", 1)
        out = signals.synthesize(self.s, now=self.now)
        corrs = [x for x in out if x["key"].startswith("corr:")]
        self.assertTrue(corrs)
        self.assertEqual(corrs[0]["key"], "corr:budget:task")  # sorted, deterministic

    def test_synthesize_is_deterministic(self):
        for d, c in [(6, 1), (4, 2), (2, 4), (0, 6)]:
            self._snap(d, "task", c)
        a = signals.synthesize(self.s, now=self.now)
        b = signals.synthesize(self.s, now=self.now)
        self.assertEqual([x["key"] for x in a], [x["key"] for x in b])

    def test_derived_keys_stable_across_calls(self):
        for d in (4, 2, 0):
            self._snap(d, "task", 1)
            self._snap(d, "budget", 1)
        keys1 = {x["key"] for x in signals.synthesize(self.s, now=self.now)}
        keys2 = {x["key"] for x in signals.synthesize(self.s, now=self.now)}
        self.assertEqual(keys1, keys2)


class ProactiveMergeTests(unittest.TestCase):
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

    def test_synthesis_setting_defaults_true(self):
        from core.settings import _defaults

        self.assertTrue(_defaults.get("pidx_proactive_synthesis", False))

    def test_merge_on_records_snapshot(self):
        from services import proactive

        out = proactive._gather_with_synthesis(
            self.s, [_sig("task", "t1")], {"pidx_proactive_synthesis": True}
        )
        self.assertEqual(self.s.query(db.SignalSnapshot).count(), 1)
        self.assertTrue(any(x["key"] == "t1" for x in out))  # originals preserved

    def test_merge_off_no_snapshot(self):
        from services import proactive

        out = proactive._gather_with_synthesis(
            self.s, [_sig("task", "t1")], {"pidx_proactive_synthesis": False}
        )
        self.assertEqual(self.s.query(db.SignalSnapshot).count(), 0)
        self.assertEqual([x["key"] for x in out], ["t1"])


if __name__ == "__main__":
    unittest.main()
