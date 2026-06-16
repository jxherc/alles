import json
import unittest
from datetime import datetime

from services import recur


def D(s):
    return datetime.fromisoformat(s)


def ev(**kw):
    base = {"start_dt": "2026-06-01T09:00", "recurrence": "", "recur_interval": 1,
            "recur_byday": "", "recur_count": None, "recur_until": None, "recur_except": "[]"}
    base.update(kw)
    return base


class RecurTests(unittest.TestCase):
    def test_single_in_and_out_of_range(self):
        e = ev()
        self.assertEqual(len(recur.expand(e, D("2026-06-01T00:00"), D("2026-06-02T00:00"))), 1)
        self.assertEqual(recur.expand(e, D("2026-07-01T00:00"), D("2026-07-02T00:00")), [])

    def test_daily_interval(self):
        e = ev(recurrence="daily", recur_interval=2)
        occ = recur.expand(e, D("2026-06-01T00:00"), D("2026-06-10T00:00"))
        self.assertEqual([d.day for d in occ], [1, 3, 5, 7, 9])

    def test_weekly_byday(self):
        # 2026-06-01 is a Monday; repeat Mon/Wed/Fri
        e = ev(recurrence="weekly", recur_byday="MO,WE,FR")
        occ = recur.expand(e, D("2026-06-01T00:00"), D("2026-06-08T00:00"))
        self.assertEqual([d.day for d in occ], [1, 3, 5])

    def test_weekly_interval_2(self):
        e = ev(recurrence="weekly", recur_interval=2)   # every other monday
        occ = recur.expand(e, D("2026-06-01T00:00"), D("2026-06-30T00:00"))
        self.assertEqual([d.day for d in occ], [1, 15, 29])

    def test_count_limits_series(self):
        e = ev(recurrence="daily", recur_count=3)
        occ = recur.expand(e, D("2026-06-01T00:00"), D("2026-12-01T00:00"))
        self.assertEqual([d.day for d in occ], [1, 2, 3])

    def test_until_limits_series(self):
        e = ev(recurrence="daily", recur_until="2026-06-03")
        occ = recur.expand(e, D("2026-06-01T00:00"), D("2026-12-01T00:00"))
        self.assertEqual([d.day for d in occ], [1, 2, 3])

    def test_except_skips_occurrence(self):
        e = ev(recurrence="daily", recur_except=json.dumps(["2026-06-02"]))
        occ = recur.expand(e, D("2026-06-01T00:00"), D("2026-06-04T00:00"))
        self.assertEqual([d.day for d in occ], [1, 3])

    def test_count_counts_pre_exclusion(self):
        # COUNT=3 with the 2nd excluded → still ends at the 3rd generated (so days 1,3)
        e = ev(recurrence="daily", recur_count=3, recur_except=json.dumps(["2026-06-02"]))
        occ = recur.expand(e, D("2026-06-01T00:00"), D("2026-12-01T00:00"))
        self.assertEqual([d.day for d in occ], [1, 3])

    def test_monthly_clamps_day(self):
        e = ev(start_dt="2026-01-31T09:00", recurrence="monthly")
        occ = recur.expand(e, D("2026-01-01T00:00"), D("2026-04-01T00:00"))
        # jan 31, feb 28 (clamped), mar 31
        self.assertEqual([(d.month, d.day) for d in occ], [(1, 31), (2, 28), (3, 31)])


if __name__ == "__main__":
    unittest.main()
