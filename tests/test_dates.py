import unittest
from datetime import date
from types import SimpleNamespace

from routes import days as D
from routes import subscriptions as S
from routes import today as T


class DaysTests(unittest.TestCase):
    def test_yearly_occurrence_and_nth(self):
        occ, nth = D._occurrence(date(2000, 3, 15), date(2026, 1, 1), "yearly")
        self.assertEqual(occ, date(2026, 3, 15))
        self.assertEqual(nth, 26)

    def test_yearly_rolls_to_next_year_when_passed(self):
        occ, nth = D._occurrence(date(2000, 3, 15), date(2026, 6, 1), "yearly")
        self.assertEqual(occ, date(2027, 3, 15))
        self.assertEqual(nth, 27)

    def test_feb29_clamps_on_non_leap(self):
        occ, _ = D._occurrence(date(2000, 2, 29), date(2026, 1, 1), "yearly")
        self.assertEqual(occ, date(2026, 2, 28))

    def test_monthly_occurrence(self):
        occ, _ = D._occurrence(date(2026, 1, 10), date(2026, 6, 5), "monthly")
        self.assertEqual(occ, date(2026, 6, 10))

    def test_ymd_between(self):
        self.assertEqual(
            D._ymd_between(date(2026, 1, 1), date(2027, 3, 13)), "1 year 2 months 12 days"
        )

    def test_ordinal(self):
        self.assertEqual(
            [D._ordinal(n) for n in (1, 2, 3, 4, 11, 21, 22)],
            ["st", "nd", "rd", "th", "th", "st", "nd"],
        )


class SubsRolloverTests(unittest.TestCase):
    def test_add_months_clamps(self):
        self.assertEqual(S._add_months(date(2026, 1, 31), 1), date(2026, 2, 28))
        self.assertEqual(S._add_months(date(2026, 11, 15), 3), date(2027, 2, 15))

    def test_advance(self):
        self.assertEqual(S._advance(date(2026, 6, 14), "weekly", 0), date(2026, 6, 21))
        self.assertEqual(S._advance(date(2026, 6, 14), "monthly", 0), date(2026, 7, 14))
        self.assertEqual(S._advance(date(2026, 6, 14), "yearly", 0), date(2027, 6, 14))
        self.assertEqual(S._advance(date(2026, 6, 14), "custom", 10), date(2026, 6, 24))

    def test_roll_advances_into_future(self):
        sub = SimpleNamespace(active=True, next_due="2026-01-01", cycle="monthly", cycle_days=30)
        self.assertTrue(S._roll(sub, date(2026, 6, 5)))
        self.assertGreaterEqual(S._parse(sub.next_due), date(2026, 6, 5))


class TodayRecurrenceTests(unittest.TestCase):
    def _ev(self, start, rec="", until=None):
        return SimpleNamespace(start_dt=start, recurrence=rec, recur_until=until)

    def test_one_off(self):
        self.assertTrue(T._event_occurs_on(self._ev("2026-06-14"), date(2026, 6, 14)))
        self.assertFalse(T._event_occurs_on(self._ev("2026-06-14"), date(2026, 6, 15)))

    def test_weekly_same_weekday(self):
        e = self._ev("2026-06-14", "weekly")
        self.assertTrue(T._event_occurs_on(e, date(2026, 6, 21)))  # +7 days
        self.assertFalse(T._event_occurs_on(e, date(2026, 6, 20)))

    def test_daily_respects_until(self):
        e = self._ev("2026-06-14", "daily", "2026-06-16")
        self.assertTrue(T._event_occurs_on(e, date(2026, 6, 16)))
        self.assertFalse(T._event_occurs_on(e, date(2026, 6, 17)))

    def test_before_start_is_false(self):
        self.assertFalse(T._event_occurs_on(self._ev("2026-06-14", "daily"), date(2026, 6, 13)))


if __name__ == "__main__":
    unittest.main()
