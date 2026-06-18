import unittest
from datetime import date
from services.task_nl import parse_task, advance

T = date(2026, 6, 14)  # fixed "today" for determinism


class ParseTests(unittest.TestCase):
    def test_tomorrow(self):
        p = parse_task("call mom tomorrow", T)
        self.assertEqual(p["due_date"], "2026-06-15")
        self.assertEqual(p["title"], "call mom")

    def test_priority_and_tags(self):
        p = parse_task("submit report #work !", T)
        self.assertEqual(p["priority"], 1)
        self.assertEqual(p["tags"], "work")
        self.assertEqual(p["title"], "submit report")

    def test_every_month_on_day(self):
        p = parse_task("pay rent every 1st", T)
        self.assertEqual(p["repeat"], "monthly")
        self.assertEqual(p["due_date"], "2026-07-01")  # 1st already passed this month
        self.assertEqual(p["title"], "pay rent")

    def test_every_week(self):
        p = parse_task("water plants every week", T)
        self.assertEqual(p["repeat"], "weekly")
        self.assertEqual(p["title"], "water plants")

    def test_in_n_weeks(self):
        p = parse_task("renew passport in 3 weeks", T)
        self.assertEqual(p["due_date"], "2026-07-05")
        self.assertEqual(p["title"], "renew passport")

    def test_iso_date(self):
        p = parse_task("buy gift 2026-12-25", T)
        self.assertEqual(p["due_date"], "2026-12-25")

    def test_weekday_is_future_and_correct(self):
        p = parse_task("standup friday", T)
        d = date.fromisoformat(p["due_date"])
        self.assertEqual(d.weekday(), 4)  # friday
        self.assertGreater(d, T)

    def test_plain_title(self):
        p = parse_task("just a normal task", T)
        self.assertIsNone(p["due_date"])
        self.assertEqual(p["repeat"], "")
        self.assertEqual(p["title"], "just a normal task")


class AdvanceTests(unittest.TestCase):
    def test_advances(self):
        self.assertEqual(advance("2026-06-14", "daily"), "2026-06-15")
        self.assertEqual(advance("2026-06-14", "weekly"), "2026-06-21")
        self.assertEqual(advance("2026-06-14", "monthly"), "2026-07-14")
        self.assertEqual(advance("2026-06-14", "yearly"), "2027-06-14")

    def test_leap_day_yearly(self):
        self.assertEqual(advance("2024-02-29", "yearly"), "2025-02-28")

    def test_no_repeat(self):
        self.assertIsNone(advance("2026-06-14", ""))
        self.assertIsNone(advance("", "daily"))


if __name__ == "__main__":
    unittest.main()
