import unittest
from datetime import date

from core.database import Contact
from routes.contacts import _days_until_birthday
from tests._client import ApiTest

T = date(2026, 6, 18)


class DaysUntilTests(unittest.TestCase):
    def test_today(self):
        self.assertEqual(_days_until_birthday("1990-06-18", T), 0)

    def test_tomorrow(self):
        self.assertEqual(_days_until_birthday("2000-06-19", T), 1)

    def test_wraps_to_next_year(self):
        self.assertEqual(_days_until_birthday("1980-06-17", T), 364)

    def test_mm_dd_format(self):
        self.assertEqual(_days_until_birthday("06-20", T), 2)

    def test_partial_dashes(self):
        self.assertEqual(_days_until_birthday("--06-20", T), 2)

    def test_invalid(self):
        self.assertIsNone(_days_until_birthday("not a date", T))

    def test_empty(self):
        self.assertIsNone(_days_until_birthday("", T))

    def test_leap_day_birthday_doesnt_crash(self):
        # Feb 29 birthday seen from a leap year, before the date → next occurrence is
        # in a non-leap year. used to raise ValueError (date(2027,2,29)); now clamps to 28.
        leap_today = date(2028, 6, 1)  # 2028 is a leap year, after Feb
        du = _days_until_birthday("2000-02-29", leap_today)
        self.assertIsNotNone(du)
        # 2029 isn't leap → Feb 28; from 2028-06-01 that's ~272 days out
        self.assertEqual(du, (date(2029, 2, 28) - leap_today).days)


class BirthdaysApiTests(ApiTest):
    def setUp(self):
        super().setUp()
        d = self.db()
        d.add_all(
            [
                Contact(name="Soon", birthday="2000-06-20"),  # in 2 days
                Contact(name="Later", birthday="1990-09-01"),  # >30 days
                Contact(name="Today", birthday="1985-06-18"),  # 0 days
                Contact(name="NoBday", birthday=""),
            ]
        )
        d.commit()
        d.close()

    def _b(self, **p):
        p.setdefault("today", "2026-06-18")
        return self.client.get("/api/contacts/birthdays", params=p).json()

    def test_within_window_sorted(self):
        names = [b["name"] for b in self._b(days=30)]
        self.assertEqual(names, ["Today", "Soon"])  # 0 then 2 days

    def test_excludes_outside_window(self):
        self.assertNotIn("Later", [b["name"] for b in self._b(days=30)])

    def test_excludes_no_birthday(self):
        self.assertNotIn("NoBday", [b["name"] for b in self._b(days=365)])

    def test_days_until_field(self):
        soon = [b for b in self._b(days=30) if b["name"] == "Soon"][0]
        self.assertEqual(soon["days_until"], 2)

    def test_wide_window_includes_later(self):
        self.assertIn("Later", [b["name"] for b in self._b(days=120)])

    def test_junk_today_param_doesnt_crash(self):
        # a bad ?today= used to 500 — now it falls back to the real today
        r = self.client.get("/api/contacts/birthdays", params={"today": "garbage", "days": 30})
        self.assertEqual(r.status_code, 200)


if __name__ == "__main__":
    unittest.main()
