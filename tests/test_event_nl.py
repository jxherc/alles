import unittest
from datetime import date
from services.event_nl import parse_event, _extract_time

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


if __name__ == "__main__":
    unittest.main()
