"""stage 4b - life-tracking stats (correlation, habit risk, health anomalies). tests first (RED)."""

import datetime
import os
import unittest

os.environ["AUTH_ENABLED"] = "false"
from services import life_stats as ls


class SpearmanTests(unittest.TestCase):
    def test_perfect_positive(self):
        self.assertAlmostEqual(ls.spearman([1, 2, 3, 4], [10, 20, 30, 40]), 1.0, places=4)

    def test_perfect_negative(self):
        self.assertAlmostEqual(ls.spearman([1, 2, 3, 4], [40, 30, 20, 10]), -1.0, places=4)

    def test_monotonic_nonlinear_is_one(self):
        self.assertAlmostEqual(ls.spearman([1, 2, 3, 4], [1, 4, 9, 16]), 1.0, places=4)

    def test_too_few_points(self):
        self.assertIsNone(ls.spearman([1, 2], [3, 4]))

    def test_no_variance(self):
        self.assertIsNone(ls.spearman([1, 2, 3], [5, 5, 5]))


class MoodTests(unittest.TestCase):
    def test_mood_ordering(self):
        self.assertGreater(ls.mood_score("happy"), ls.mood_score("sad"))
        self.assertGreater(ls.mood_score("great"), ls.mood_score("meh"))

    def test_unknown_mood_neutral(self):
        self.assertEqual(ls.mood_score("zxcv"), 3)


class CorrelateTests(unittest.TestCase):
    def test_correlate_output(self):
        pairs = [(1, 2), (2, 4), (3, 6), (4, 8), (5, 10)]
        out = ls.correlate(pairs)
        self.assertAlmostEqual(out["rho"], 1.0, places=4)
        self.assertEqual(out["n"], 5)
        self.assertEqual(out["direction"], "positive")
        self.assertIn(out["strength"], ("strong", "moderate", "weak", "none"))


class HabitRiskTests(unittest.TestCase):
    TODAY = datetime.date(2026, 6, 23)

    def test_high_risk_when_recent_misses(self):
        # only did it once in the last 14 days
        done = ["2026-06-10"]
        out = ls.habit_failure_risk(done, self.TODAY, window=14)
        self.assertGreater(out["risk"], 0.6)

    def test_low_risk_when_consistent(self):
        done = [(self.TODAY - datetime.timedelta(days=i)).isoformat() for i in range(1, 15)]
        out = ls.habit_failure_risk(done, self.TODAY, window=14)
        self.assertLess(out["risk"], 0.3)

    def test_reason_present(self):
        out = ls.habit_failure_risk([], self.TODAY, window=14)
        self.assertTrue(out["reason"])


class HealthTests(unittest.TestCase):
    def test_baseline(self):
        b = ls.health_baseline([10, 12, 14])
        self.assertAlmostEqual(b["mean"], 12.0, places=4)
        self.assertEqual(b["n"], 3)
        self.assertGreater(b["std"], 0)

    def test_anomaly_flagged(self):
        series = [
            ("2026-06-01", 70.0),
            ("2026-06-02", 71.0),
            ("2026-06-03", 70.5),
            ("2026-06-04", 70.2),
            ("2026-06-05", 95.0),
        ]  # last is an outlier
        anoms = ls.health_anomalies(series, k=2.0)
        self.assertTrue(any(a["date"] == "2026-06-05" for a in anoms))

    def test_no_anomaly_when_stable(self):
        series = [("d1", 70.0), ("d2", 70.1), ("d3", 69.9), ("d4", 70.05)]
        self.assertEqual(ls.health_anomalies(series, k=2.0), [])


if __name__ == "__main__":
    unittest.main()
