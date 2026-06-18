import unittest
from datetime import date

from services.event_nl import _extract_time, parse_event

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

    def test_malformed_iso_date_does_not_crash(self):
        # an impossible date must not reach date.fromisoformat() and 500;
        # it should fall back to an all-day event today, keeping the text as title
        p = parse_event("file taxes 2026-13-40", T)
        self.assertEqual(p["start_dt"], "2026-06-14")
        self.assertIn("file taxes", p["title"])


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
