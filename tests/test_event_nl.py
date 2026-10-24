import unittest
from datetime import date

from services.event_nl import NotADate, _extract_time, parse_event
from tests._client import ApiTest

T = date(2026, 6, 14)


class TimeTests(unittest.TestCase):
    def test_variants(self):
        self.assertEqual(_extract_time("at 1pm")[0].hour, 13)
        self.assertEqual(_extract_time("9am")[0].hour, 9)
        t, _ = _extract_time("9:30pm")
        self.assertEqual((t.hour, t.minute), (21, 30))
        self.assertEqual(_extract_time("13:00")[0].hour, 13)
        self.assertEqual(_extract_time("noon")[0].hour, 12)
        self.assertIsNone(_extract_time("no time here")[0])


class EventTests(unittest.TestCase):
    def test_timed_event(self):
        p = parse_event("call bob tomorrow 3pm", T)
        self.assertFalse(p["all_day"])
        self.assertEqual(p["start_dt"], "2026-06-15T15:00")
        self.assertEqual(p["end_dt"], "2026-06-15T16:00")
        self.assertEqual(p["title"], "call bob")

    def test_keeps_with(self):
        p = parse_event("lunch with sam friday 1pm", T)
        self.assertEqual(p["title"], "lunch with sam")
        self.assertTrue(p["start_dt"].endswith("T13:00"))

    def test_month_name_date_with_time(self):
        # F13: this module's own docstring example used to land on today, not june 20
        p = parse_event("dentist june 20 9:30am", T)
        self.assertEqual(p["start_dt"], "2026-06-20T09:30")
        self.assertEqual(p["title"], "dentist")

    def test_all_day_when_no_time(self):
        p = parse_event("team sync tomorrow", T)
        self.assertTrue(p["all_day"])
        self.assertEqual(p["start_dt"], "2026-06-15")
        self.assertEqual(p["title"], "team sync")

    def test_iso_datetime(self):
        p = parse_event("meeting 2026-07-01 10:00", T)
        self.assertEqual(p["start_dt"], "2026-07-01T10:00")
        self.assertEqual(p["title"], "meeting")

    def test_plain_title_defaults_today_allday(self):
        p = parse_event("buy milk", T)
        self.assertTrue(p["all_day"])
        self.assertEqual(p["start_dt"], "2026-06-14")
        self.assertEqual(p["title"], "buy milk")

    def test_malformed_iso_date_is_refused_not_moved_to_today(self):
        with self.assertRaisesRegex(NotADate, "2026-13-40 isn't a date"):
            parse_event("file taxes 2026-13-40", T)

    def test_dates_and_times_that_dont_exist_are_refused(self):
        friday = date(2026, 10, 23)
        for text, reason in (
            ("lunch feb 30", "feb 30 isn't a date"),
            ("lunch apr 31", "apr 31 isn't a date"),
            ("dinner 31 jun", "31 jun isn't a date"),
            ("lunch feb 29", "feb 29 isn't a date in 2027"),
            ("meeting 25:00", "25:00 isn't a time"),
            ("call 12:60", "12:60 isn't a time"),
            ("lunch 1:75pm", "1:75pm isn't a time"),
            ("lunch 13pm", "13pm isn't a time"),
            ("party 2026-13-45", "2026-13-45 isn't a date"),
        ):
            with self.subTest(text=text), self.assertRaises(NotADate) as caught:
                parse_event(text, friday)
            self.assertEqual(str(caught.exception), reason)

    def test_an_odd_h_mm_is_text_when_a_real_time_is_there(self):
        wednesday = date(2026, 10, 21)
        p = parse_event("bible study matthew 28:19 7pm", wednesday)
        self.assertEqual(
            (p["start_dt"], p["title"]), ("2026-10-21T19:00", "bible study matthew 28:19")
        )
        p = parse_event("noon lunch 28:19 ref", wednesday)
        self.assertEqual(p["start_dt"], "2026-10-21T12:00")
        # alone, or right after "at", it was meant as the time
        for text in ("bible study matthew 28:19", "meet at 25:00 re q3"):
            with self.subTest(text=text), self.assertRaises(NotADate):
                parse_event(text, wednesday)

    def test_until_a_day_without_a_repeat_is_just_the_day(self):
        p = parse_event("until fri finish essay", date(2026, 10, 21))
        self.assertEqual(
            (p["start_dt"], p["title"], p["recur_until"]), ("2026-10-23", "finish essay", None)
        )
        p = parse_event("standup every monday until dec 1", date(2026, 10, 21))
        self.assertEqual(
            (p["start_dt"], p["recurrence"], p["recur_until"], p["title"]),
            ("2026-10-26", "weekly", "2026-12-01", "standup"),
        )

    def test_a_dot_between_hour_and_minutes_is_a_time(self):
        friday = date(2026, 10, 23)
        p = parse_event("dinner 12.30pm", friday)
        self.assertEqual((p["start_dt"], p["title"]), ("2026-10-23T12:30", "dinner"))
        p = parse_event("lunch 1.30-2.30pm", friday)
        self.assertEqual((p["start_dt"], p["end_dt"]), ("2026-10-23T13:30", "2026-10-23T14:30"))
        with self.assertRaisesRegex(NotADate, "9.75pm isn't a time"):
            parse_event("call 9.75pm", friday)

    def test_weekdays_read_like_tasks(self):
        friday = date(2026, 10, 23)
        for text, start, title in (
            ("next week monday standup", "2026-10-26", "standup"),
            ("buy sun screen", "2026-10-23", "buy sun screen"),
            ("every sun water plants", "2026-10-25", "water plants"),
            ("every fri 5pm drinks", "2026-10-30T17:00", "drinks"),
            # a short day as the first word, or tue/thu/fri anywhere, is the day
            ("fri dinner 7pm", "2026-10-30T19:00", "dinner"),
            ("mon standup 9am", "2026-10-26T09:00", "standup"),
            ("sat brunch 11am", "2026-10-24T11:00", "brunch"),
            ("tue dentist", "2026-10-27", "dentist"),
            ("wed team lunch", "2026-10-28", "team lunch"),
            ("sun brunch with family", "2026-10-25", "brunch with family"),
            ("dinner fri with sam", "2026-10-30", "dinner with sam"),
            ("next week fri review", "2026-10-30", "review"),
            ("on monday: standup", "2026-10-26", "standup"),
            ("until fri finish essay", "2026-10-30", "finish essay"),
        ):
            with self.subTest(text=text):
                p = parse_event(text, friday)
                self.assertEqual((p["start_dt"], p["title"]), (start, title))

    def test_a_line_with_no_when_says_so(self):
        friday = date(2026, 10, 23)
        self.assertTrue(parse_event("asdf", friday)["no_date"])
        # "may 45 people" isn't a date, so it's plain text
        self.assertTrue(parse_event("may 45 people come", friday)["no_date"])
        for text in ("lunch 1pm", "team sync tomorrow", "standup daily", "lunch feb 29 2028"):
            with self.subTest(text=text):
                self.assertFalse(parse_event(text, friday)["no_date"])


class RecurrenceTests(unittest.TestCase):
    def test_daily(self):
        p = parse_event("standup daily 9am", T)
        self.assertEqual(p["recurrence"], "daily")
        self.assertTrue(p["start_dt"].endswith("T09:00"))
        self.assertEqual(p["title"], "standup")

    def test_every_week(self):
        p = parse_event("review every week", T)
        self.assertEqual(p["recurrence"], "weekly")
        self.assertEqual(p["title"], "review")

    def test_every_weekday_keeps_day_for_first_occurrence(self):
        p = parse_event("yoga every monday 6pm", T)
        self.assertEqual(p["recurrence"], "weekly")
        self.assertEqual(p["start_dt"], "2026-06-15T18:00")  # next monday after sat 6/14
        self.assertEqual(p["title"], "yoga")

    def test_until_clause(self):
        p = parse_event("class every week until 2026-08-01", T)
        self.assertEqual(p["recurrence"], "weekly")
        self.assertEqual(p["recur_until"], "2026-08-01")
        self.assertEqual(p["title"], "class")

    def test_until_without_cycle_ignored(self):
        p = parse_event("trip until 2026-08-01", T)
        self.assertEqual(p["recurrence"], "")
        self.assertIsNone(p["recur_until"])

    def test_no_recurrence(self):
        p = parse_event("call bob tomorrow 3pm", T)
        self.assertEqual(p["recurrence"], "")
        self.assertIsNone(p["recur_until"])


def _dur(p):
    from datetime import datetime

    s = datetime.fromisoformat(p["start_dt"])
    e = datetime.fromisoformat(p["end_dt"])
    return int((e - s).total_seconds() // 60)


class DurationTests(unittest.TestCase):
    def test_for_hours(self):
        p = parse_event("lunch tomorrow 1pm for 2 hours", T)
        self.assertEqual(_dur(p), 120)
        self.assertNotIn("for", p["title"].lower())

    def test_for_minutes(self):
        self.assertEqual(_dur(parse_event("call tomorrow 9am for 30 minutes", T)), 30)

    def test_for_90_min(self):
        self.assertEqual(_dur(parse_event("meeting tomorrow 10am for 90 min", T)), 90)

    def test_short_unit_h(self):
        self.assertEqual(_dur(parse_event("workout tomorrow 6am for 1h", T)), 60)

    def test_default_one_hour(self):
        self.assertEqual(_dur(parse_event("standup tomorrow 9am", T)), 60)

    def test_duration_without_time_is_all_day(self):
        self.assertTrue(parse_event("review docs for 2 hours", T)["all_day"])


class RangeTests(unittest.TestCase):
    def test_range_shared_meridiem(self):
        p = parse_event("meeting tomorrow 1-2pm", T)
        self.assertTrue(p["start_dt"].endswith("T13:00"))
        self.assertTrue(p["end_dt"].endswith("T14:00"))

    def test_range_explicit(self):
        p = parse_event("demo tomorrow 3pm to 4:30pm", T)
        self.assertTrue(p["start_dt"].endswith("T15:00"))
        self.assertTrue(p["end_dt"].endswith("T16:30"))

    def test_range_am(self):
        p = parse_event("yoga tomorrow 9-10am", T)
        self.assertTrue(p["start_dt"].endswith("T09:00"))
        self.assertTrue(p["end_dt"].endswith("T10:00"))


if __name__ == "__main__":
    unittest.main()


class QuickAddApiTest(ApiTest):
    def test_a_date_that_doesnt_exist_is_a_400_with_the_reason(self):
        r = self.client.post("/api/calendar/quick", json={"text": "lunch feb 30"})
        self.assertEqual(r.status_code, 400)
        self.assertEqual(r.json()["detail"], "feb 30 isn't a date")
        self.assertEqual(self.client.get("/api/calendar").json(), [])

    def test_text_with_no_date_lands_today_and_says_so(self):
        r = self.client.post("/api/calendar/quick", json={"text": "asdf"})
        self.assertEqual(r.status_code, 200, r.text)
        self.assertEqual(r.headers.get("x-alles-no-date"), "1")
        self.assertTrue(r.json()["all_day"])
        self.assertNotIn("no_date", r.json())
        r = self.client.post("/api/calendar/quick", json={"text": "lunch tomorrow 1pm"})
        self.assertIsNone(r.headers.get("x-alles-no-date"))
