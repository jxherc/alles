import unittest
from datetime import date

from services.task_nl import advance, parse_task
from tests._client import ApiTest

T = date(2026, 6, 14)  # fixed "today" for determinism


class ParseTests(unittest.TestCase):
    def test_tomorrow(self):
        p = parse_task("call mom tomorrow", T)
        self.assertEqual(p["due_date"], "2026-06-15")
        self.assertEqual(p["title"], "call mom")

    def test_possessive_dates_keep_the_title_and_suggest_the_same_due_date(self):
        for phrase, due in (
            ("today", "2026-06-14"),
            ("tomorrow", "2026-06-15"),
            ("Friday", "2026-06-19"),
            ("next Monday", "2026-06-15"),
        ):
            for apostrophe in ("'", "’"):
                with self.subTest(phrase=phrase, apostrophe=apostrophe):
                    title = f"prepare {phrase}{apostrophe}s reading"
                    parsed = parse_task(title, T)
                    self.assertEqual(parsed["title"], title)
                    self.assertEqual(parsed["due_date"], due)

    def test_plain_date_instructions_still_leave_only_the_task_title(self):
        for phrase, due in (
            ("today", "2026-06-14"),
            ("tomorrow", "2026-06-15"),
            ("Friday", "2026-06-19"),
            ("next Monday", "2026-06-15"),
        ):
            with self.subTest(phrase=phrase):
                parsed = parse_task(f"prepare reading {phrase}", T)
                self.assertEqual(parsed["title"], "prepare reading")
                self.assertEqual(parsed["due_date"], due)

    def test_priority_and_tags(self):
        p = parse_task("submit report #work !", T)
        self.assertEqual(p["priority"], 2)  # single ! = med on the 0-3 scale
        self.assertEqual(p["tags"], "work")
        self.assertEqual(p["title"], "submit report")

    def test_double_bang_is_high(self):
        # !! must not collapse to the same level as ! (the bug); it's high (3)
        p = parse_task("call mom tomorrow !!", T)
        self.assertEqual(p["priority"], 3)
        self.assertEqual(p["title"], "call mom")

    def test_month_name_date(self):
        # F13: month-name dates used to never parse, so the task silently lost its due date
        p = parse_task("submit report june 20", T)
        self.assertEqual(p["due_date"], "2026-06-20")
        self.assertEqual(p["title"], "submit report")

    def test_month_name_day_first(self):
        p = parse_task("party 20 june", T)
        self.assertEqual(p["due_date"], "2026-06-20")
        self.assertEqual(p["title"], "party")

    def test_month_name_abbrev_with_ordinal(self):
        p = parse_task("renew passport dec 25th", T)
        self.assertEqual(p["due_date"], "2026-12-25")

    def test_month_name_past_rolls_to_next_year(self):
        # jan 3 is before the fixed today (jun 14 2026) -> next year's jan
        p = parse_task("taxes jan 3", T)
        self.assertEqual(p["due_date"], "2027-01-03")

    def test_month_name_explicit_year(self):
        p = parse_task("deadline june 20 2027", T)
        self.assertEqual(p["due_date"], "2027-06-20")

    def test_month_name_bare_year_is_not_a_day(self):
        # "june 2027" has no day-of-month — must NOT read "20" out of "2027" as the day
        p = parse_task("plan trip june 2027", T)
        self.assertIsNone(p["due_date"])
        self.assertIn("2027", p["title"])  # the text is left intact, not half-eaten

    def test_every_month_on_day(self):
        p = parse_task("pay rent every 1st", T)
        self.assertEqual(p["repeat"], "monthly")
        self.assertEqual(p["due_date"], "2026-07-01")  # 1st already passed this month
        self.assertEqual(p["title"], "pay rent")

    def test_every_31st_clamps_to_month_end(self):
        # used to flatten to the 28th; june has no 31st so the first hit is the 30th
        p = parse_task("pay rent every 31st", T)
        self.assertEqual(p["repeat"], "monthly")
        self.assertEqual(p["due_date"], "2026-06-30")

    def test_every_30th_this_month(self):
        p = parse_task("pay rent every 30th", T)
        self.assertEqual(p["due_date"], "2026-06-30")

    def test_every_0th_does_not_crash(self):
        # junk input shouldn't 500 via date.replace(day=0)
        p = parse_task("do thing every 0th", T)
        self.assertEqual(p["repeat"], "monthly")
        self.assertTrue(p["due_date"])

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


class PastDayTests(unittest.TestCase):
    def test_last_weekday_is_the_one_that_went_by(self):
        friday = date(2026, 10, 23)
        r = parse_task("fix bike tire last friday", today=friday)
        self.assertEqual((r["title"], r["due_date"]), ("fix bike tire", "2026-10-16"))
        self.assertEqual(parse_task("call last monday", today=friday)["due_date"], "2026-10-19")

    def test_yesterday(self):
        r = parse_task("call bank yesterday", today=date(2026, 10, 23))
        self.assertEqual((r["title"], r["due_date"]), ("call bank", "2026-10-22"))

    def test_a_past_day_never_steals_the_real_due_date(self):
        friday = date(2026, 10, 23)
        for text, title, due in (
            ("follow up on yesterday's call friday", "follow up on yesterday's call", "2026-10-30"),
            (
                "ask about last thursday's invoice next tuesday",
                "ask about last thursday's invoice",
                "2026-10-27",
            ),
            ("review what we did yesterday june 30", "review what we did yesterday", "2027-06-30"),
            ("follow up on yesterday’s call", "follow up on yesterday’s call", None),
            ("ask about last thursday's invoice", "ask about last thursday's invoice", None),
            ("go over yesterday notes on monday", "go over yesterday notes", "2026-10-26"),
            ("send yesterday photos friday", "send yesterday photos", "2026-10-30"),
            (
                "call about last friday invoice tuesday",
                "call about last friday invoice",
                "2026-10-27",
            ),
            (
                "call about last  friday invoice tuesday",
                "call about last friday invoice",
                "2026-10-27",
            ),
        ):
            with self.subTest(text=text):
                r = parse_task(text, today=friday)
                self.assertEqual((r["title"], r["due_date"]), (title, due))


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


class WeekdayPlacementTests(unittest.TestCase):
    friday = date(2026, 10, 23)

    def test_next_week_with_a_weekday_is_that_day_next_week(self):
        for text, title, due in (
            ("next week monday standup", "standup", "2026-10-26"),
            ("monday standup next week", "standup", "2026-10-26"),
            ("standup next week on tue", "standup", "2026-10-27"),
            ("review next week friday", "review", "2026-10-30"),
            ("next week fri review", "review", "2026-10-30"),
            ("next week mon standup", "standup", "2026-10-26"),
        ):
            with self.subTest(text=text):
                r = parse_task(text, today=self.friday)
                self.assertEqual((r["title"], r["due_date"]), (title, due))

    def test_a_short_weekday_inside_a_phrase_is_not_a_day(self):
        for text, title, due in (
            ("buy sun screen", "buy sun screen", None),
            ("pack sun hat", "pack sun hat", None),
            ("sat exam prep", "exam prep", "2026-10-24"),  # the first word is where a day goes
            ("meet on sat", "meet", "2026-10-24"),
            ("call mom fri", "call mom", "2026-10-30"),
            ("wed 9am dentist", "9am dentist", "2026-10-28"),
            ("submit report by friday", "submit report", "2026-10-30"),
            ("call mom this friday", "call mom", "2026-10-30"),
            ("water plants every sun", "water plants", "2026-10-25"),
            ("On Monday: standup", "standup", "2026-10-26"),
            ("until fri finish essay", "finish essay", "2026-10-30"),
            ("due friday: report", "report", "2026-10-30"),
        ):
            with self.subTest(text=text):
                r = parse_task(text, today=self.friday)
                self.assertEqual((r["title"], r["due_date"]), (title, due))

    def test_a_short_weekday_first_or_tue_thu_fri_anywhere_is_the_day(self):
        for text, title, due in (
            ("fri dinner", "dinner", "2026-10-30"),
            ("mon standup", "standup", "2026-10-26"),
            ("sat brunch", "brunch", "2026-10-24"),
            ("tue dentist", "dentist", "2026-10-27"),
            ("wed team lunch", "team lunch", "2026-10-28"),
            ("sun brunch with family", "brunch with family", "2026-10-25"),
            ("dinner fri with sam", "dinner with sam", "2026-10-30"),
            ("haircut thu with ana", "haircut with ana", "2026-10-29"),
        ):
            with self.subTest(text=text):
                r = parse_task(text, today=self.friday)
                self.assertEqual((r["title"], r["due_date"]), (title, due))

    def test_strict_refuses_a_date_that_does_not_exist(self):
        from services.task_nl import NotADate

        for text, reason in (
            ("pay rent feb 30", "feb 30 isn't a date"),
            ("renew 2026-13-45", "2026-13-45 isn't a date"),
            ("party feb 29", "feb 29 isn't a date in 2027"),
        ):
            with self.subTest(text=text), self.assertRaises(NotADate) as caught:
                parse_task(text, today=self.friday, strict=True)
            self.assertEqual(str(caught.exception), reason)
        # without strict (mail capture, the nl create path) it still clamps quietly
        self.assertEqual(parse_task("pay rent feb 30", today=self.friday)["due_date"], "2027-02-28")


class QuickAddRefusalApiTest(ApiTest):
    def test_task_quick_add_refuses_a_date_that_does_not_exist(self):
        for preview in (False, True):
            r = self.client.post(
                "/api/tasks/quick", json={"text": "pay rent feb 30", "preview": preview}
            )
            self.assertEqual(r.status_code, 400, r.text)
            self.assertEqual(r.json()["detail"], "feb 30 isn't a date")
        self.assertEqual(self.client.get("/api/tasks").json(), [])
        ok = self.client.post("/api/tasks/quick", json={"text": "pay rent feb 28"})
        self.assertEqual(ok.status_code, 200, ok.text)
